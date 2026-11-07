#!/usr/bin/env python3
"""
On-Demand Supermarket Search CLI (wrapper for Personal Agent / Hermes Skill).
Reuses SUPERMARKETS and extract_page from extract_supermarkets.py and
parse_semantic_context from analyze_promos.py with zero code duplication and
without touching data.json or seen_promos.json used by the weekly cron job.
"""
import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.request
from playwright.async_api import async_playwright

from extract_supermarkets import SUPERMARKETS, extract_page
from analyze_promos import parse_semantic_context

STORE_ALIASES = {
    "ah": "Albert Heijn",
    "albert heijn": "Albert Heijn",
    "albertheijn": "Albert Heijn",
    "colruyt": "Colruyt",
    "collect&go": "Colruyt",
    "collectandgo": "Colruyt",
    "delhaize": "Delhaize",
}


def is_cdp_ready(port=9222):
    try:
        with urllib.request.urlopen(f"http://localhost:{port}/json/version", timeout=1.5) as resp:
            return resp.status == 200
    except Exception:
        return False


def ensure_browser_running():
    """Starts Xvfb + Chrome on port 9222 if not already running. Returns subprocess if started by us."""
    if is_cdp_ready(9222):
        return None

    profile_dir = os.path.expanduser("~/.config/chrome-ah-profile")
    os.makedirs(profile_dir, exist_ok=True)

    cmd = [
        "xvfb-run", "-a", "--server-args=-screen 0 1920x1080x24",
        "google-chrome-stable",
        "--ozone-platform=x11",
        "--remote-debugging-port=9222",
        f"--user-data-dir={profile_dir}",
        "--window-size=1920,1080",
        "about:blank"
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(20):
        if is_cdp_ready(9222):
            return proc
        time.sleep(0.5)
    return proc


def resolve_stores(stores_arg):
    if not stores_arg or stores_arg.strip().lower() in ("all", "alle", "*"):
        return SUPERMARKETS

    requested = set()
    for part in stores_arg.split(","):
        key = part.strip().lower()
        if key in STORE_ALIASES:
            requested.add(STORE_ALIASES[key])
        else:
            for s in SUPERMARKETS:
                if key in s["name"].lower():
                    requested.add(s["name"])

    selected = [s for s in SUPERMARKETS if s["name"] in requested]
    return selected if selected else SUPERMARKETS


async def run_search(queries, stores, only_promos=False):
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://localhost:9222")
        contexts = browser.contexts
        page = contexts[0].pages[0] if contexts and contexts[0].pages else await browser.new_page()

        all_items = []
        seen_links = set()

        for store in stores:
            for query in queries:
                items = await extract_page(page, store, query, seen_links)
                for item in items:
                    parsed = parse_semantic_context(item.get("semantic_context", []))
                    if only_promos and not parsed["is_promo"]:
                        continue
                    all_items.append({
                        "supermarket": item["supermarket"],
                        "search_query": item["search_query"],
                        "is_promo": parsed["is_promo"],
                        "promotion": parsed["promotion"],
                        "title": parsed["title"],
                        "unit_price": parsed["unit_price"],
                        "unit": parsed["unit"],
                        "link": item["link"],
                    })
                await asyncio.sleep(0.5)

        return all_items


def format_markdown_report(items, queries, stores, only_promos):
    store_names = ", ".join(s["name"] for s in stores)
    query_str = ", ".join(queries)
    promos = [i for i in items if i["is_promo"]]

    lines = [
        f"### Supermarket Search Results ({store_names})",
        f"- **Queries:** {query_str}",
        f"- **Found:** {len(items)} products ({len(promos)} with active promotion)",
        ""
    ]

    for store in stores:
        s_name = store["name"]
        s_items = [i for i in items if i["supermarket"] == s_name]
        s_promos = [i for i in s_items if i["is_promo"]]
        s_regular = [i for i in s_items if not i["is_promo"]]

        lines.append(f"#### 🛒 {s_name}")
        if not s_items:
            lines.append("- No matching products found.")
            lines.append("")
            continue

        if s_promos:
            lines.append("**🔥 Active Promotions:**")
            for p in s_promos:
                unit_str = f" ({p['unit']})" if p["unit"] else ""
                lines.append(
                    f"- **PROMO [{p['promotion']}]** {p['title']} — {p['unit_price']}{unit_str}"
                )
        else:
            lines.append("- *No active promotions found for this query.*")

        if not only_promos and s_regular:
            lines.append(f"**Standard Prices (top {min(len(s_regular), 8)} of {len(s_regular)}):**")
            for r in s_regular[:8]:
                unit_str = f" ({r['unit']})" if r["unit"] else ""
                lines.append(f"- {r['title']} — {r['unit_price']}{unit_str}")
        lines.append("")

    return "\n".join(lines).strip()


def main():
    parser = argparse.ArgumentParser(
        description="Live price and promotion search across Albert Heijn, Colruyt, and Delhaize."
    )
    parser.add_argument(
        "--queries", "-q", required=True,
        help="Comma-separated search terms, e.g. 'skyr,kipfilet' or 'barebells'"
    )
    parser.add_argument(
        "--stores", "-s", default="all",
        help="Comma-separated stores: ah, colruyt, delhaize, or all (default: all)"
    )
    parser.add_argument(
        "--only-promos", action="store_true",
        help="Show only products that currently have an active promotion"
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Return output as raw JSON instead of Markdown"
    )
    args = parser.parse_args()

    queries = [q.strip() for q in args.queries.split(",") if q.strip()]
    stores = resolve_stores(args.stores)

    started_proc = ensure_browser_running()
    try:
        # Redirect progress logs from extract_page to stderr so stdout stays clean for the Agent
        real_stdout = sys.stdout
        sys.stdout = sys.stderr
        try:
            items = asyncio.run(run_search(queries, stores, only_promos=args.only_promos))
        finally:
            sys.stdout = real_stdout

        if args.json:
            print(json.dumps(items, indent=2, ensure_ascii=False))
        else:
            print(format_markdown_report(items, queries, stores, args.only_promos))
    finally:
        if started_proc is not None:
            started_proc.terminate()
            subprocess.run(["pkill", "-f", "remote-debugging-port=9222"], stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    main()
