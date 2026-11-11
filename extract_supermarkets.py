import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from playwright.async_api import async_playwright

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "data.json")

# Target brands and fallback search terms for Belgian supermarkets
BRANDS = [
    "hipro",             # Captures Danone drinks, puddings, and bars
    "barebells",         # Captures bars and milkshakes
    "holie",             # Captures Holie's Chewy Bars and granola without apostrophe issues
    "melkunie protein",  # Specifically high-protein drinks and puddings from Melkunie
    "nakd protein",      # Specifically high-protein variants from Nākd
    "upfront",           # Unique brand keyword for Upfront products
    "xxl nutrition",     # Captures XXL Nutrition Fitmousse, Fitpudding, Fitshake, Fitquark, bars
    "eiwitreep",         # Dutch fallback for protein bars across other brands
    "protein bar"        # English fallback for protein bars
]

SUPERMARKETS = [
    {
        "name": "Albert Heijn",
        "url_template": "https://www.ah.be/zoeken?query={query}",
        "card_selector": '[data-testid="product-card-vertical-container"], article'
    },
    {
        "name": "Colruyt",
        "url_template": "https://www.collectandgo.be/nl/zoek?searchTerm={query}",
        "card_selector": 'a.cogo-product-tile, a[href*="/assortiment/"]'
    },
    {
        "name": "Delhaize",
        "url_template": "https://www.delhaize.be/shop/search?q={query}%3Arelevance&text={query}&sort=relevance",
        "card_selector": '[data-testid="product-block"], article'
    }
]

# Universal Semantic DOM Extractor:
# Extracts semantic fields from the DOM without duplicates (title, promo badge, unit_price, unit).
SEMANTIC_EXTRACT_JS = r"""(cardSelector) => {
    const cards = Array.from(document.querySelectorAll(cardSelector));
    const results = [];

    for (const card of cards) {
        let linkEl = card.tagName === 'A' ? card : card.querySelector('a[href]');
        let link = linkEl ? linkEl.href : '';

        const cleanText = (val) => val ? val.replace(/\s+/g, ' ').trim() : '';

        // 1. Product title from semantic heading or link
        let title = '';
        const heading = card.querySelector(
            '[data-testid="product-block-product-name"], [data-testid="product-card-text-container"], [role="heading"]'
        );
        if (heading) {
            title = cleanText(heading.getAttribute('title') || heading.innerText);
        }
        if (!title && linkEl && linkEl.getAttribute('aria-label')) {
            title = cleanText(linkEl.getAttribute('aria-label'));
        }
        if (!title) continue;

        // 2. Promotion badge from the DOM (filter out non-promo badges and future-dated promos on Belgian sites)
        const nonPromoBadges = ['nieuw', 'new', 'tip', 'servicekostactie', 'combineer naar keuze'];
        const futurePromoRegex = /\b(vanaf\s+(maandag|dinsdag|woensdag|donderdag|vrijdag|zaterdag|zondag|\d{1,2}\s+(januari|februari|maart|april|mei|juni|juli|augustus|september|oktober|november|december|jan|feb|mrt|apr|jun|jul|aug|sep|okt|nov|dec)\b)|geldig\s+vanaf)\b/i;
        const cardText = cleanText(card.innerText);
        const isFuturePromo = futurePromoRegex.test(title) || futurePromoRegex.test(cardText);

        // Clean future prefix / action suffix from AH title
        title = title.replace(/^vanaf\s+(maandag|dinsdag|woensdag|donderdag|vrijdag|zaterdag|zondag)\s+/i, '')
                     .replace(/\s+combineer\s+nu$/i, '')
                     .trim();

        const promos = [];
        if (!isFuturePromo) {
            const promoElements = card.querySelectorAll(
                '[data-testid="tag-promo-label"], [data-testid="product-card-promotion-label"], .ds-strap-line__label, [data-testid*="promo-label"]'
            );
            promoElements.forEach(p => {
                const val = cleanText(p.innerText || p.getAttribute('aria-label'));
                if (val && !nonPromoBadges.includes(val.toLowerCase()) && !futurePromoRegex.test(val) && !promos.includes(val)) {
                    promos.push(val);
                }
            });
        }

        // 3. Unit price & price per kg/l from screenreader (.sr-only) or data-testid
        let unitPrice = '';
        let unit = '';

        // Check Delhaize / AH data-testids
        const priceEl = card.querySelector('[data-testid="product-block-price"], [data-testid="product-card-current-price"]');
        if (priceEl) {
            unitPrice = cleanText(priceEl.getAttribute('aria-label') || priceEl.innerText);
        }
        const descEl = card.querySelector('[data-testid="product-block-supplementary-price"], [data-testid="product-card-price-description"]');
        if (descEl) {
            unit = cleanText(descEl.getAttribute('aria-label') || descEl.innerText);
        }
        const unitPriceEl = card.querySelector('[data-testid="product-block-price-per-unit"]');
        if (unitPriceEl) {
            const up = cleanText(unitPriceEl.innerText || unitPriceEl.getAttribute('aria-label'));
            unit = unit ? `${unit} (${up})` : up;
        }

        // Check Colruyt .sr-only spans (Dutch accessibility labels on collectandgo.be)
        card.querySelectorAll('.sr-only').forEach(sr => {
            const txt = cleanText(sr.innerText);
            if (txt.toLowerCase().includes('per stuk')) {
                unitPrice = txt;
            } else if (txt.toLowerCase().includes('per liter') || txt.toLowerCase().includes('per kilogram')) {
                unit = txt;
            }
        });

        const contextLines = [
            promos.length > 0 ? `PROMO_ACTIVE: ${promos.join(' | ')}` : `NO_PROMO (standard price)`,
            `title: ${title}`,
        ];
        if (unitPrice) contextLines.push(`unit_price: ${unitPrice}`);
        if (unit) contextLines.push(`unit: ${unit}`);

        results.push({
            link: link,
            semantic_context: contextLines
        });
    }
    return results;
}"""


def is_cdp_ready(port=9222):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1.5) as resp:
            return resp.status == 200
    except Exception:
        return False


def ensure_browser_running(port=9222):
    """Ensures Xvfb + Chrome is listening on 127.0.0.1:9222. Uses systemd service on host if available."""
    if is_cdp_ready(port):
        return None

    # Inside the Docker sandbox container, systemctl/xvfb-run do not exist; host service must provide 127.0.0.1:9222
    if os.path.exists("/.dockerenv"):
        raise RuntimeError(
            f"Chrome CDP on 127.0.0.1:{port} is not reachable from inside the Docker sandbox. "
            "Please run 'systemctl --user start chrome-cdp-xvfb.service' on the host."
        )

    # On the host, prefer starting the managed user systemd service so it stays running cleanly
    try:
        res = subprocess.run(
            ["systemctl", "--user", "start", "chrome-cdp-xvfb.service"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        if res.returncode == 0:
            for _ in range(20):
                if is_cdp_ready(port):
                    return None
                time.sleep(0.5)
    except Exception:
        pass

    profile_dir = os.path.expanduser("~/.config/chrome-ah-profile")
    os.makedirs(profile_dir, exist_ok=True)

    cmd = [
        "xvfb-run", "-a", "--server-args=-screen 0 1920x1080x24",
        "google-chrome-stable",
        "--ozone-platform=x11",
        "--remote-debugging-address=127.0.0.1",
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        "--disable-search-engine-choice-screen",
        "--window-size=1920,1080",
        "about:blank"
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(20):
        if is_cdp_ready(port):
            return proc
        time.sleep(0.5)
    return proc


async def dismiss_cookie_banner(page):
    """Attempts to automatically dismiss common cookie consent banners on Belgian supermarkets."""
    cookie_selectors = [
        "#onetrust-accept-btn-handler",
        "button:has-text('Alles accepteren')",
        "button:has-text('Alle cookies accepteren')",
        "button:has-text('Alle cookies aanvaarden')",
        "button:has-text('Accepteren')",
        "button:has-text('Accepteer cookies')",
        "button:has-text('Accepteer')",
        "button:has-text('Akkoord')",
        "button:has-text('Accept all')",
        "[data-testhook='cookie-accept-all']"
    ]
    for sel in cookie_selectors:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=800):
                print(f"  [Cookie Banner] Clicking: '{sel}'")
                await btn.click()
                await page.wait_for_timeout(600)
                return True
        except Exception:
            pass
    return False


async def scroll_smoothly(page):
    """Scrolls down smoothly so lazy-loaded product cards are rendered."""
    try:
        for _ in range(3):
            await page.evaluate("window.scrollBy(0, 700)")
            await page.wait_for_timeout(400)
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(600)
    except Exception:
        pass


async def extract_page(page, store, query, seen_links):
    encoded_query = urllib.parse.quote_plus(query)
    url = store["url_template"].format(query=encoded_query)
    print(f"\n[{store['name']}] Searching for '{query}' at: {url}")

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2200)

        await dismiss_cookie_banner(page)

        card_selector = store["card_selector"]
        try:
            await page.wait_for_selector(card_selector, timeout=5000)
        except Exception:
            pass

        await scroll_smoothly(page)

        cards = await page.evaluate(SEMANTIC_EXTRACT_JS, card_selector)

        found_items = []
        query_words = [w for w in query.lower().split() if len(w) >= 2]
        target_keywords = [
            query.lower(), *query_words, "hipro", "danone", "barebells", "holie", "melkunie",
            "nakd", "nākd", "upfront", "xxl", "fitmousse", "fitpudding", "fitshake", "fitquark",
            "protein", "proteïne", "eiwit", "reep", "bar"
        ]

        for card in cards:
            context_lines = card["semantic_context"]
            full_text = " ".join(context_lines).lower()

            if any(term in full_text for term in ["terugroepactie", "coca-cola", "savooikool"]):
                continue

            if not any(kw in full_text for kw in target_keywords):
                continue

            link = card["link"] or url
            if link in seen_links:
                continue
            seen_links.add(link)

            found_items.append({
                "supermarket": store["name"],
                "search_query": query,
                "link": link,
                "semantic_context": context_lines
            })

        print(f"  -> Saved {len(found_items)} products with semantic context.")
        return found_items

    except Exception as e:
        print(f"  [ERROR] Failed to process {store['name']} ({query}): {e}")
        return []


async def scrape_stores(queries=None, stores=None, delay=1.0):
    """Connects to Chrome on port 9222 and scrapes all specified stores and queries."""
    queries = queries if queries is not None else BRANDS
    stores = stores if stores is not None else SUPERMARKETS

    print("Connecting to Chrome on 127.0.0.1:9222...")
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        contexts = browser.contexts
        pages = [
            pg for pg in (contexts[0].pages if contexts else [])
            if not pg.url.startswith("chrome://search-engine-choice")
        ]
        page = pages[0] if pages else await browser.new_page()

        all_products = []
        seen_links = set()

        print(f"Starting semantic extraction for queries: {queries}")

        for store in stores:
            for query in queries:
                items = await extract_page(page, store, query, seen_links)
                all_products.extend(items)
                await asyncio.sleep(delay)

        return all_products


async def extract_all_stores():
    queries = ["hipro", "barebells", "eiwitreep"] if "--quick" in sys.argv else BRANDS
    try:
        all_products = await scrape_stores(queries=queries, stores=SUPERMARKETS, delay=1.0)
    except Exception as e:
        print(f"\n[ERROR] Could not connect to Chrome: {e}")
        print("Make sure Chrome is running first via: ./start_browser.sh or ./start_browser_xvfb.sh")
        return

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(all_products, f, indent=2, ensure_ascii=False)

    print("\n=======================================================")
    print(f"[COMPLETE] Total {len(all_products)} products saved with semantic context in {DATA_FILE}!")
    for store in SUPERMARKETS:
        count = sum(1 for p in all_products if p["supermarket"] == store["name"])
        print(f"  - {store['name']}: {count} products")
    print("=======================================================")


if __name__ == "__main__":
    asyncio.run(extract_all_stores())
