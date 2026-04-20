"""
sgpools_scraper.py
------------------
Scrapes Singapore Pools sports odds and horse racing odds for personal use.

Usage:
    python sgpools_scraper.py sports
    python sgpools_scraper.py horses
    python sgpools_scraper.py both
    python sgpools_scraper.py both --watch                 # poll every 5 min, append to history CSV
    python sgpools_scraper.py sports --watch --interval 600 # custom interval (seconds)
    python sgpools_scraper.py sports --headed              # show the browser window (debugging)

Output:
    ./output/sports_<UTC-timestamp>.csv     (snapshot mode)
    ./output/horses_<UTC-timestamp>.csv
    ./output/sports_history.csv             (watch mode, appended)
    ./output/horses_history.csv

Legal / polite-use note:
    This script is for personal tracking of publicly displayed odds. Singapore Pools'
    Terms of Use may restrict automated access -- check before deploying at scale.
    Do not remove the delay between requests, and do not run this from many IPs in
    parallel. Keep the default interval at >= 5 minutes.
"""

import argparse
import asyncio
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import Page, TimeoutError as PWTimeout, async_playwright

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SPORTS_URL = "https://online.singaporepools.com/en/sports"
HORSES_URL = "https://online.singaporepools.com/en/horse-racing"

# A realistic desktop-Chrome UA. Update yearly so it does not go stale.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

OUTPUT_DIR = Path("./output")

# Polite pause (seconds) after the page loads before we read DOM, and between
# navigations. Do not set to 0.
POST_LOAD_PAUSE = 2.5
BETWEEN_PAGES_PAUSE = 3.0

# ---------------------------------------------------------------------------
# *** SELECTORS YOU MUST VERIFY IN CHROME DEVTOOLS ***
# ---------------------------------------------------------------------------
# Singapore Pools changes its front-end markup periodically, so the selectors
# below are my best-guess starting points. Please verify them before trusting
# the output. Procedure:
#
#   1. Open https://online.singaporepools.com/en/sports in Chrome.
#   2. Wait for the odds to appear.
#   3. Right-click one match row (the whole row for one fixture) -> Inspect.
#   4. In DevTools look at the highlighted element. Note its tag + class, e.g.
#        <div class="match-row ...">
#   5. Right-click the element in the Elements panel -> Copy -> Copy selector.
#      Paste it below into SPORTS_MATCH_ROW_SELECTOR.
#   6. Do the same for: the team/competitors text, the odds cells, the league
#      / competition header, and the kickoff time.
#   7. Repeat on https://online.singaporepools.com/en/horse-racing for each
#      horse row, horse name, jockey, and win/place odds.
#
# If a selector returns zero elements when you run the script, see the
# troubleshooting section in the README-style block at the bottom of this file.
# ---------------------------------------------------------------------------

# --- Sports page selectors (VERIFY) ---
SPORTS_MATCH_ROW_SELECTOR = 'div[class*="match"]'          # one row per fixture
SPORTS_LEAGUE_SELECTOR = '[class*="league"], [class*="competition"]'  # league header (optional)
SPORTS_TEAMS_SELECTOR = '[class*="team"], [class*="participant"]'     # team names inside row
SPORTS_ODDS_SELECTOR = '[class*="odds"], button'                      # odds cells inside row
SPORTS_TIME_SELECTOR = '[class*="time"], [class*="date"]'             # kickoff time inside row

# --- Horse racing page selectors (VERIFY) ---
HORSE_RACE_HEADER_SELECTOR = '[class*="race"][class*="header"], [class*="meeting"]'  # race # / venue
HORSE_ROW_SELECTOR = 'tr, [class*="horse-row"], [class*="runner"]'   # one row per horse
HORSE_NUMBER_SELECTOR = '[class*="number"], td:nth-child(1)'
HORSE_NAME_SELECTOR = '[class*="horse-name"], [class*="runner-name"], td:nth-child(2)'
HORSE_JOCKEY_SELECTOR = '[class*="jockey"]'
HORSE_WIN_ODDS_SELECTOR = '[class*="win"]'
HORSE_PLACE_ODDS_SELECTOR = '[class*="place"]'

# CSV columns
SPORTS_FIELDS = ["scraped_at_utc", "league", "kickoff", "home", "away", "odds_raw"]
HORSES_FIELDS = ["scraped_at_utc", "race", "horse_no", "horse_name", "jockey", "win_odds", "place_odds"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_stamp_for_filename() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def write_rows(rows: list[dict], target: Path, fields: list[str], append: bool) -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    new_file = not target.exists()
    mode = "a" if append else "w"
    with target.open(mode, newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        if new_file or not append:
            writer.writeheader()
        for row in rows:
            writer.writerow(row)
    print(f"[ok] wrote {len(rows)} rows -> {target}")


def text_of(el) -> str:
    """Playwright ElementHandle -> stripped text, or empty string."""
    try:
        t = el.inner_text()
        return " ".join(t.split()) if t else ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Scrapers
# ---------------------------------------------------------------------------

async def scrape_sports(page: Page) -> list[dict]:
    print(f"[..] loading {SPORTS_URL}")
    await page.goto(SPORTS_URL, wait_until="domcontentloaded", timeout=45_000)
    try:
        await page.wait_for_load_state("networkidle", timeout=15_000)
    except PWTimeout:
        pass  # some pages keep long-poll connections alive; do not fail here
    await asyncio.sleep(POST_LOAD_PAUSE)

    rows_out: list[dict] = []
    now = utc_now_iso()

    match_handles = await page.query_selector_all(SPORTS_MATCH_ROW_SELECTOR)
    print(f"[..] found {len(match_handles)} candidate match rows")

    for row in match_handles:
        league_el = await row.query_selector(SPORTS_LEAGUE_SELECTOR)
        time_el = await row.query_selector(SPORTS_TIME_SELECTOR)
        team_els = await row.query_selector_all(SPORTS_TEAMS_SELECTOR)
        odds_els = await row.query_selector_all(SPORTS_ODDS_SELECTOR)

        teams = [(await t.inner_text()).strip() for t in team_els if t]
        odds = [(await o.inner_text()).strip() for o in odds_els if o]

        # Filter obvious noise: rows with no teams and no odds are not real fixtures.
        if not teams and not odds:
            continue

        rows_out.append({
            "scraped_at_utc": now,
            "league": (await league_el.inner_text()).strip() if league_el else "",
            "kickoff": (await time_el.inner_text()).strip() if time_el else "",
            "home": teams[0] if len(teams) > 0 else "",
            "away": teams[1] if len(teams) > 1 else "",
            "odds_raw": " | ".join(o for o in odds if o),
        })

    return rows_out


async def scrape_horses(page: Page) -> list[dict]:
    print(f"[..] loading {HORSES_URL}")
    await page.goto(HORSES_URL, wait_until="domcontentloaded", timeout=45_000)
    try:
        await page.wait_for_load_state("networkidle", timeout=15_000)
    except PWTimeout:
        pass
    await asyncio.sleep(POST_LOAD_PAUSE)

    rows_out: list[dict] = []
    now = utc_now_iso()

    # Race header (race number / meeting name). We associate every horse row
    # with the nearest preceding header. If the page structure is simple
    # (single race visible), this is fine.
    header_el = await page.query_selector(HORSE_RACE_HEADER_SELECTOR)
    race_label = (await header_el.inner_text()).strip() if header_el else ""

    horse_handles = await page.query_selector_all(HORSE_ROW_SELECTOR)
    print(f"[..] found {len(horse_handles)} candidate horse rows")

    for row in horse_handles:
        name_el = await row.query_selector(HORSE_NAME_SELECTOR)
        if not name_el:
            continue  # skip header rows, empty rows, etc.
        name = (await name_el.inner_text()).strip()
        if not name:
            continue

        no_el = await row.query_selector(HORSE_NUMBER_SELECTOR)
        jockey_el = await row.query_selector(HORSE_JOCKEY_SELECTOR)
        win_el = await row.query_selector(HORSE_WIN_ODDS_SELECTOR)
        place_el = await row.query_selector(HORSE_PLACE_ODDS_SELECTOR)

        rows_out.append({
            "scraped_at_utc": now,
            "race": race_label,
            "horse_no": (await no_el.inner_text()).strip() if no_el else "",
            "horse_name": name,
            "jockey": (await jockey_el.inner_text()).strip() if jockey_el else "",
            "win_odds": (await win_el.inner_text()).strip() if win_el else "",
            "place_odds": (await place_el.inner_text()).strip() if place_el else "",
        })

    return rows_out


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

async def run_once(mode: str, headed: bool, history: bool) -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not headed)
        context = await browser.new_context(
            user_agent=USER_AGENT,
            locale="en-SG",
            timezone_id="Asia/Singapore",
            viewport={"width": 1366, "height": 900},
        )
        page = await context.new_page()
        try:
            if mode in ("sports", "both"):
                rows = await scrape_sports(page)
                target = (
                    OUTPUT_DIR / "sports_history.csv"
                    if history
                    else OUTPUT_DIR / f"sports_{utc_stamp_for_filename()}.csv"
                )
                write_rows(rows, target, SPORTS_FIELDS, append=history)

                if mode == "both":
                    await asyncio.sleep(BETWEEN_PAGES_PAUSE)

            if mode in ("horses", "both"):
                rows = await scrape_horses(page)
                target = (
                    OUTPUT_DIR / "horses_history.csv"
                    if history
                    else OUTPUT_DIR / f"horses_{utc_stamp_for_filename()}.csv"
                )
                write_rows(rows, target, HORSES_FIELDS, append=history)
        finally:
            await context.close()
            await browser.close()


async def watch_loop(mode: str, interval: int, headed: bool) -> None:
    print(f"[..] watch mode: every {interval}s, Ctrl+C to stop")
    while True:
        started = datetime.now(timezone.utc)
        try:
            await run_once(mode, headed=headed, history=True)
        except Exception as exc:
            # Never let one failed poll kill the loop.
            print(f"[err] scrape failed: {exc!r}", file=sys.stderr)
        elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        sleep_for = max(5.0, interval - elapsed)
        print(f"[..] sleeping {sleep_for:.0f}s until next poll")
        await asyncio.sleep(sleep_for)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Scrape Singapore Pools odds.")
    p.add_argument("mode", choices=["sports", "horses", "both"])
    p.add_argument("--watch", action="store_true",
                   help="Poll repeatedly and append to a single history CSV.")
    p.add_argument("--interval", type=int, default=300,
                   help="Seconds between polls in --watch mode (default 300 = 5 min).")
    p.add_argument("--headed", action="store_true",
                   help="Show the browser (useful for debugging selectors).")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    if args.watch:
        asyncio.run(watch_loop(args.mode, args.interval, args.headed))
    else:
        asyncio.run(run_once(args.mode, headed=args.headed, history=False))


if __name__ == "__main__":
    main()
