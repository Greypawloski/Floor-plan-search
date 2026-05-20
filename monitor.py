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


def check_availability() -> None:
    # Imports are here so .env is already loaded before they run
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

    previous = load_state()
    newly_available = find_new_availabilities(previous, current)

    if newly_available:
        log.info("NEW availability detected: %d plan(s)", len(newly_available))
        for p in newly_available:
            log.info("  • %s  [%s]", p.name, p.availability_text)
        send_email_notification(newly_available, URL)
    else:
        available_count = sum(1 for p in current if p.available)
        log.info(
            "No new availability. %d/%d plan(s) currently available.",
            available_count,
            len(current),
        )

    save_state(current)


def main() -> None:
    parser = argparse.ArgumentParser(description='Floor plan availability monitor')
    parser.add_argument('--once', action='store_true', help='Check once and exit')
    parser.add_argument('--reset', action='store_true', help='Clear saved state before running')
    args = parser.parse_args()

    if args.reset:
        if os.path.exists('state.json'):
            os.remove('state.json')
            log.info("State cleared.")

    if args.once:
        check_availability()
        return

    log.info("Floor plan monitor started — checking every %d minute(s)", CHECK_INTERVAL)
    log.info("URL: %s", URL)
    log.info("Press Ctrl+C to stop.\n")

    # Run immediately, then on schedule
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
