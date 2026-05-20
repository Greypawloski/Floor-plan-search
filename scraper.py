import logging
import re
from dataclasses import dataclass, asdict
from typing import Optional

log = logging.getLogger(__name__)

# Keywords that confirm a unit is actually available to lease
_AVAILABLE_SIGNALS = [
    r'\bavailable now\b',
    r'\bapply now\b',
    r'\bschedule a tour\b',
    r'\bschedule tour\b',
    r'\b[1-9]\d*\s+available\b',   # "2 available", "3 available"
    r'\bavailable\b',
]

# Keywords that indicate a unit is NOT available
_UNAVAILABLE_SIGNALS = [
    r'\bwaitlist\b',
    r'\bwait list\b',
    r'\bnot available\b',
    r'\bcoming soon\b',
    r'\b0 available\b',
    r'\bno units available\b',
    r'\bfully leased\b',
]


@dataclass
class FloorPlan:
    name: str
    details: str       # raw descriptive text (bed/bath/sqft/price)
    available: bool
    availability_text: str  # the specific phrase that triggered detection

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> 'FloorPlan':
        return FloorPlan(**d)


def _is_available(text: str) -> tuple[bool, str]:
    """Returns (is_available, matched_phrase)."""
    lower = text.lower()
    for pattern in _UNAVAILABLE_SIGNALS:
        m = re.search(pattern, lower)
        if m:
            return False, m.group()
    for pattern in _AVAILABLE_SIGNALS:
        m = re.search(pattern, lower)
        if m:
            return True, m.group()
    return False, ''


def scrape_floor_plans(url: str) -> Optional[list[FloorPlan]]:
    """
    Uses a headless Chromium browser to load the floor plans page and extract
    availability info. Returns None on unrecoverable error.
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        log.error("playwright is not installed. Run: pip install playwright && playwright install chromium")
        return None

    try:
        from playwright_stealth import stealth_sync
        _has_stealth = True
    except ImportError:
        _has_stealth = False
        log.debug("playwright_stealth not available; proceeding without it")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-dev-shm-usage',
            ]
        )
        context = browser.new_context(
            user_agent=(
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/124.0.0.0 Safari/537.36'
            ),
            viewport={'width': 1280, 'height': 900},
            locale='en-US',
        )
        page = context.new_page()

        if _has_stealth:
            stealth_sync(page)

        try:
            page.goto(url, wait_until='networkidle', timeout=45000)
        except PWTimeout:
            log.warning("Page load timed out (networkidle); trying domcontentloaded fallback")
            try:
                page.goto(url, wait_until='domcontentloaded', timeout=30000)
                page.wait_for_timeout(4000)   # let JS render
            except PWTimeout:
                log.error("Page failed to load entirely")
                browser.close()
                return None

        # Extra wait for JS-rendered content
        page.wait_for_timeout(3000)

        plans = (
            _extract_by_selectors(page)
            or _extract_by_text_blocks(page)
        )

        if not plans:
            log.warning("Could not parse individual floor plans; falling back to full-page change detection")
            plans = _extract_full_page_fallback(page)

        browser.close()
        log.info("Scraped %d floor plan entries", len(plans))
        return plans


# ---------------------------------------------------------------------------
# Extraction strategies (tried in order)
# ---------------------------------------------------------------------------

def _extract_by_selectors(page) -> list[FloorPlan]:
    """Try common CSS patterns used by apartment-site platforms (Entrata, Yardi, etc.)."""
    candidate_selectors = [
        '[class*="floorplan"]',
        '[class*="floor-plan"]',
        '[class*="FloorPlan"]',
        '[class*="fp-"]',
        '[data-floorplan]',
        '.plan-card',
        '.unit-type',
        '.plan-item',
        '.floor-plan-item',
    ]

    for selector in candidate_selectors:
        try:
            elements = page.query_selector_all(selector)
        except Exception:
            continue

        if not elements:
            continue

        plans: list[FloorPlan] = []
        for el in elements:
            try:
                text = el.inner_text().strip()
            except Exception:
                continue
            if not text or len(text) < 10:
                continue

            name = _guess_plan_name(text)
            available, phrase = _is_available(text)
            plans.append(FloorPlan(
                name=name,
                details=text[:600],
                available=available,
                availability_text=phrase,
            ))

        if plans:
            log.debug("Extracted %d plans via selector '%s'", len(plans), selector)
            return plans

    return []


def _extract_by_text_blocks(page) -> list[FloorPlan]:
    """
    Walk the page text line by line, grouping lines into floor-plan chunks
    whenever bed/bath/sqft keywords appear.
    """
    try:
        body_text = page.inner_text('body')
    except Exception:
        return []

    lines = [l.strip() for l in body_text.splitlines() if l.strip()]
    plan_triggers = re.compile(
        r'(studio|\d[\s-]*bed|\bbr\b|\bbath\b|sq\.?\s*ft\.?|\$\d{3,})',
        re.IGNORECASE,
    )

    plans: list[FloorPlan] = []
    used: set[int] = set()
    for i, line in enumerate(lines):
        if i in used or not plan_triggers.search(line):
            continue
        chunk_lines = lines[max(0, i - 1): min(len(lines), i + 10)]
        chunk = '\n'.join(chunk_lines)
        used.update(range(max(0, i - 1), min(len(lines), i + 10)))

        name = _guess_plan_name(chunk)
        available, phrase = _is_available(chunk)
        if name or available or phrase:
            plans.append(FloorPlan(
                name=name,
                details=chunk[:600],
                available=available,
                availability_text=phrase,
            ))

    return plans


def _extract_full_page_fallback(page) -> list[FloorPlan]:
    """
    Last resort: treat the entire page as a single entry.
    We'll detect ANY change in the page content as a potential availability change.
    """
    try:
        text = page.inner_text('body')
    except Exception:
        text = ''
    available, phrase = _is_available(text)
    return [FloorPlan(
        name='Full page snapshot',
        details=text[:2000],
        available=available,
        availability_text=phrase,
    )]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PLAN_NAME_RE = re.compile(
    r'('
    r'penthouse\s*\d*'           # Penthouse 1, Penthouse 2, Penthouse
    r'|ph[-\s]?\d+'              # PH1, PH-1, PH 1
    r'|[a-z]\d{1,3}'            # B10, A1, C12 — letter + number plan codes
    r'|studio'
    r'|[a-z]\d?[\s/-]*plan'
    r'|plan\s*[a-z\d]+'
    r'|\d[\s-]*bed(?:room)?s?(?:\s*/\s*\d[\s-]*bath)?'
    r')',
    re.IGNORECASE,
)


def _guess_plan_name(text: str) -> str:
    # Prefer the first recognizable plan identifier in the text
    for m in _PLAN_NAME_RE.finditer(text):
        candidate = m.group().strip()
        if len(candidate) >= 2:
            return candidate
    first_line = text.splitlines()[0].strip()
    return first_line[:60] if first_line else 'Unknown Plan'
