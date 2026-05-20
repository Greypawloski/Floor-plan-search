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
import logging
import os
import re
import sys
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

# Comma-separated plan names from .env, e.g. "B10,Penthouse 1,Penthouse 2"
_WATCH_PLANS_RAW = os.getenv('WATCH_PLANS', '')


def _build_watch_patterns() -> list[re.Pattern]:
    """
    Turn each entry in WATCH_PLANS into a regex that matches it as a substring,
    case-insensitively. Spaces and hyphens are treated as interchangeable.
    Examples:
      "B10"         -> matches "Plan B10", "B-10", "b10"
      "Penthouse 1" -> matches "Penthouse 1", "Penthouse-1", "penthouse1"
      "PH1"         -> matches "PH1", "PH-1", "ph 1"
    """
    patterns = []
    for raw in _WATCH_PLANS_RAW.split(','):
        name = raw.strip()
        if not name:
            continue
        # Build a flexible pattern:
        #   1. Existing spaces/hyphens → optional [\s-]?
        #   2. Letter→digit or digit→letter boundaries → optional [\s-]?
        #      so "B10" matches "B10", "B-10", "B 10"
        escaped = re.escape(name)
        # Collapse escaped spaces/hyphens into optional separator
        flexible = re.sub(r'(\\ |\\-)+', r'[\\s\\-]?', escaped)
        # Insert optional separator at letter↔digit transitions
        flexible = re.sub(r'(?<=[a-zA-Z])(?=\\d|[0-9])', r'[\\s\\-]?', flexible)
        flexible = re.sub(r'(?<=\\d)(?=[a-zA-Z])|(?<=[0-9])(?=[a-zA-Z])', r'[\\s\\-]?', flexible)
        patterns.append(re.compile(flexible, re.IGNORECASE))
    return patterns


_WATCH_PATTERNS = _build_watch_patterns()


def _matches_watch_list(plan) -> bool:
    """Return True if this plan should be watched (matches any configured name)."""
    if not _WATCH_PATTERNS:
        return True   # no filter configured → watch everything
    text = plan.name + '\n' + plan.details
    return any(p.search(text) for p in _WATCH_PATTERNS)


def check_availability() -> None:
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

    # Narrow to only the floor plans we care about
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


def main() -> None:
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
    log.info("Press Ctrl+C to stop.\n")

    check_availability()
    schedule.every(CHECK_INTERVAL).minutes.do(check_availability)

    try:
        while True:
            schedule.run_pending()
            time.sleep(20)
    except KeyboardInterrupt:
        log.info("Monitor stopped.")


if __name__ == '__main__':
    main()
