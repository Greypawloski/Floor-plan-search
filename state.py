import json
import hashlib
import logging
import os
from scraper import FloorPlan

log = logging.getLogger(__name__)
STATE_FILE = 'state.json'


def load_state() -> list[FloorPlan]:
    if not os.path.exists(STATE_FILE):
        return []
    try:
        with open(STATE_FILE) as f:
            data = json.load(f)
        return [FloorPlan.from_dict(d) for d in data]
    except Exception as e:
        log.warning("Could not load state file: %s", e)
        return []


def save_state(plans: list[FloorPlan]) -> None:
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump([p.to_dict() for p in plans], f, indent=2)
    except IOError as e:
        log.error("Could not save state: %s", e)


def _plan_key(plan: FloorPlan) -> str:
    """Stable key representing a floor plan's identity and content."""
    return hashlib.sha1(plan.details.encode()).hexdigest()


def find_new_availabilities(previous: list[FloorPlan], current: list[FloorPlan]) -> list[FloorPlan]:
    """
    Returns floor plans that are newly available compared to the previous check.
    On first run (empty previous), returns all currently available plans.
    """
    if not previous:
        available = [p for p in current if p.available]
        log.info("First run: %d available plan(s) found", len(available))
        return available

    prev_available_keys = {_plan_key(p) for p in previous if p.available}

    newly_available = [
        p for p in current
        if p.available and _plan_key(p) not in prev_available_keys
    ]
    return newly_available
