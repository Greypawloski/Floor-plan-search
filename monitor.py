#!/usr/bin/env python3
"""
Floor Plan Availability Monitor
Checks a leasing website on a schedule and emails you when units become available.

Usage:
  python monitor.py            # run continuously (uses CHECK_INTERVAL_MINUTES from .env)
  python monitor.py --once     # check once and exit (good for testing)
  python monitor.py --reset    # delete saved state and start fresh
"""

import argparse
import http.server
import logging
import os
import re
import signal
import sys
import threading
import time

import schedule
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)-8s  %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('monitor.log', encoding='utf-8'),
    ],
)
log = logging.getLogger(__name__)

URL = os.getenv('FLOOR_PLAN_URL', 'https://7600broadway.com/floorplans/')
CHECK_INTERVAL = int(os.getenv('CHECK_INTERVAL_MINUTES', '5'))

_WATCH_PLANS_RAW = os.getenv('WATCH_PLANS', '')

_stop_event = threading.Event()
_check_lock = threading.Lock()


def _build_watch_patterns() -> list[re.Pattern]:
    patterns = []
    for raw in _WATCH_PLANS_RAW.split(','):
        name = raw.strip()
        if not name:
            continue
        escaped = re.escape(name)
        flexible = re.sub(r'(\\ |\\-)+', r'[\\s\\-]?', escaped)
        flexible = re.sub(r'(?<=[a-zA-Z])(?=\\d|[0-9])', r'[\\s\\-]?', flexible)
        flexible = re.sub(r'(?<=\\d)(?=[a-zA-Z])|(?<=[0-9])(?=[a-zA-Z])', r'[\\s\\-]?', flexible)
        patterns.append(re.compile(flexible, re.IGNORECASE))
    return patterns


_WATCH_PATTERNS = _build_watch_patterns()


def _matches_watch_list(plan) -> bool:
    if not _WATCH_PATTERNS:
        return True
    text = plan.name + '\n' + plan.details
    return any(p.search(text) for p in _WATCH_PATTERNS)


def check_availability() -> None:
    if not _check_lock.acquire(blocking=False):
        log.info("Previous check still running — skipping this cycle")
        return
    try:
        _do_check()
    finally:
        _check_lock.release()


def _do_check() -> None:
    from notifier import send_email_notification
    from scraper import scrape_floor_plans
    from state import find_new_availabilities, load_state, save_state

    log.info("Checking: %s", URL)
    try:
        current = scrape_floor_plans(URL)
    except Exception as e:
        log.error("Scraper raised an unexpected error: %s", e, exc_info=True)
        return

    if current is None:
        log.warning("Scraper returned no data — skipping this check")
        return

    watched = [p for p in current if _matches_watch_list(p)]

    if _WATCH_PATTERNS and len(watched) < len(current):
        log.info(
            "Watch list active: %d/%d scraped plan(s) match [%s]",
            len(watched),
            len(current),
            _WATCH_PLANS_RAW,
        )

    previous = load_state()
    newly_available = find_new_availabilities(previous, watched)

    if newly_available:
        log.info("NEW availability detected: %d plan(s)", len(newly_available))
        for p in newly_available:
            log.info("  • %s  [%s]", p.name, p.availability_text)
        send_email_notification(newly_available, URL)
    else:
        available_count = sum(1 for p in watched if p.available)
        log.info(
            "No new availability. %d/%d watched plan(s) currently available.",
            available_count,
            len(watched),
        )

    save_state(watched)


def _start_health_server() -> None:
    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'OK')
        def log_message(self, *args):
            pass
    server = http.server.HTTPServer(('0.0.0.0', 8080), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log.info("Health check server listening on :8080")


def _handle_shutdown(signum, frame):
    log.info("Shutdown signal received — waiting for any active check to finish...")
    _stop_event.set()


def main() -> None:
    _start_health_server()

    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)

    parser = argparse.ArgumentParser(description='Floor plan availability monitor')
    parser.add_argument('--once', action='store_true', help='Check once and exit')
    parser.add_argument('--reset', action='store_true', help='Clear saved state before running')
    args = parser.parse_args()

    if args.reset:
        if os.path.exists('state.json'):
            os.remove('state.json')
            log.info("State cleared.")

    if _WATCH_PATTERNS:
        log.info(
            "Watching only: %s",
            ', '.join(r.strip() for r in _WATCH_PLANS_RAW.split(',') if r.strip()),
        )
    else:
        log.info("No watch list set — monitoring ALL floor plans")

    if args.once:
        check_availability()
        return

    log.info("Monitor started — checking every %d minute(s)", CHECK_INTERVAL)
    log.info("URL: %s", URL)

    from notifier import send_confirmation_email
    try:
        send_confirmation_email(_WATCH_PLANS_RAW or 'All plans', URL)
    except Exception as e:
        log.error("Confirmation email error: %s", e, exc_info=True)

    check_availability()
    schedule.every(CHECK_INTERVAL).minutes.do(check_availability)

    while not _stop_event.is_set():
        schedule.run_pending()
        time.sleep(20)

    # Wait for any in-progress check to finish before exiting
    _check_lock.acquire(timeout=90)
    log.info("Monitor stopped cleanly.")


if __name__ == '__main__':
    main()
