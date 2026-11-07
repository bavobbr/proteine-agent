#!/usr/bin/env python3
"""
On-Demand Supermarkt Zoeker (CLI wrapper voor Personal Agent / Hermes Skill).
Hergebruikt SUPERMARKTEN en extract_page uit extract_supermarkten.py en
parse_semantic_context uit analyseer_promos.py zonder code-duplicatie en
zonder data.json of seen_promos.json van de wekelijkse cronjob aan te raken.
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

from extract_supermarkten import SUPERMARKTEN, extract_page
from analyseer_promos import parse_semantic_context

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
    """Start Xvfb + Chrome op poort 9222 als die nog niet actief is. Geeft subprocess terug indien zelf gestart."""
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
        return SUPERMARKTEN

    requested = set()
    for part in stores_arg.split(","):
        key = part.strip().lower()
        if key in STORE_ALIASES:
            requested.add(STORE_ALIASES[key])
        else:
            for s in SUPERMARKTEN:
                if key in s["naam"].lower():
                    requested.add(s["naam"])

    selected = [s for s in SUPERMARKTEN if s["naam"] in requested]
    return selected if selected else SUPERMARKTEN


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
                    parsed = parse_semantic_context(item.get("semantische_context", []))
                    if only_promos and not parsed["is_promo"]:
                        continue
                    all_items.append({
                        "supermarkt": item["supermarkt"],
                        "zoekterm": item["zoekterm"],
                        "is_promo": parsed["is_promo"],
                        "promotie": parsed["promotie"],
                        "titel": parsed["titel"],
                        "stukprijs": parsed["stukprijs"],
                        "eenheid": parsed["eenheid"],
                        "link": item["link"],
                    })
                await asyncio.sleep(0.5)

        return all_items


def format_markdown_report(items, queries, stores, only_promos):
    store_names = ", ".join(s["naam"] for s in stores)
    query_str = ", ".join(queries)
    promos = [i for i in items if i["is_promo"]]

    lines = [
        f"### Zoekresultaat Supermarkten ({store_names})",
        f"- **Zoektermen:** {query_str}",
        f"- **Gevonden:** {len(items)} producten ({len(promos)} met actieve promotie)",
        ""
    ]

    for store in stores:
        s_name = store["naam"]
        s_items = [i for i in items if i["supermarkt"] == s_name]
        s_promos = [i for i in s_items if i["is_promo"]]
        s_regular = [i for i in s_items if not i["is_promo"]]

        lines.append(f"#### 🛒 {s_name}")
        if not s_items:
            lines.append("- Geen bijpassende producten gevonden.")
            lines.append("")
            continue

        if s_promos:
            lines.append("**🔥 Actieve Promoties:**")
            for p in s_promos:
                eenheid_str = f" ({p['eenheid']})" if p["eenheid"] else ""
                lines.append(
                    f"- **PROMO [{p['promotie']}]** {p['titel']} — {p['stukprijs']}{eenheid_str}"
                )
        else:
            lines.append("- *Geen actieve promoties gevonden voor deze zoekopdracht.*")

        if not only_promos and s_regular:
            lines.append(f"**Standaardprijzen (top {min(len(s_regular), 8)} van {len(s_regular)}):**")
            for r in s_regular[:8]:
                eenheid_str = f" ({r['eenheid']})" if r["eenheid"] else ""
                lines.append(f"- {r['titel']} — {r['stukprijs']}{eenheid_str}")
        lines.append("")

    return "\n".join(lines).strip()


def main():
    parser = argparse.ArgumentParser(
        description="Zoek live naar prijzen en promoties bij Albert Heijn, Colruyt en Delhaize."
    )
    parser.add_argument(
        "--queries", "-q", required=True,
        help="Komma-gescheiden zoektermen, bijv. 'skyr,kipfilet' of 'barebells'"
    )
    parser.add_argument(
        "--stores", "-s", default="all",
        help="Komma-gescheiden winkels: ah, colruyt, delhaize of all (standaard: all)"
    )
    parser.add_argument(
        "--only-promos", action="store_true",
        help="Toon uitsluitend producten die momenteel in promotie staan"
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Geef output terug als ruwe JSON i.p.v. Markdown"
    )
    args = parser.parse_args()

    queries = [q.strip() for q in args.queries.split(",") if q.strip()]
    stores = resolve_stores(args.stores)

    started_proc = ensure_browser_running()
    try:
        # Stuur voortgangslogs van extract_page naar stderr zodat stdout zuiver blijft voor de Agent
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
