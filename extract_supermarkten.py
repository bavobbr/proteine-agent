import asyncio
import json
import sys
import urllib.parse
from playwright.async_api import async_playwright

# Doelmerken en vangnet-zoektermen voor de supermarkten
MERKEN = [
    "hipro",             # Vangt alle Danone dranken, puddings en repen
    "barebells",         # Vangt de repen en milkshakes
    "holie",             # Vangt Holie's Chewy Bars en granola zonder apostrof-issues
    "melkunie protein",  # Specifiek eiwitrijke dranken en puddings van Melkunie
    "nakd protein",      # Specifiek de eiwitrijke varianten van Nākd
    "upfront",           # Uniek merkwoord voor Upfront producten
    "eiwitreep",         # Vangnet voor losse aanbiedingen op vergeten merken
    "protein bar"        # Vangnet voor Engelstalige labels
]

SUPERMARKTEN = [
    {
        "naam": "Albert Heijn",
        "url_template": "https://www.ah.be/zoeken?query={query}",
        "card_selector": '[data-testid="product-card-vertical-container"], article'
    },
    {
        "naam": "Colruyt",
        "url_template": "https://www.collectandgo.be/nl/zoek?searchTerm={query}",
        "card_selector": 'a.cogo-product-tile, a[href*="/assortiment/"]'
    },
    {
        "naam": "Delhaize",
        "url_template": "https://www.delhaize.be/shop/search?q={query}%3Arelevance&text={query}&sort=relevance",
        "link_pattern": "/shop/",
        "card_selector": '[data-testid="product-block"], article'
    }
]

# Universele Semantische DOM Extractor:
# Haalt zonder duplicaten de exacte semantische velden uit de DOM (titel, actie_badge, stukprijs, eenheid).
SEMANTIC_EXTRACT_JS = r"""(cardSelector) => {
    const cards = Array.from(document.querySelectorAll(cardSelector));
    const results = [];

    for (const card of cards) {
        let linkEl = card.tagName === 'A' ? card : card.querySelector('a[href]');
        let link = linkEl ? linkEl.href : '';

        const cleanText = (val) => val ? val.replace(/\s+/g, ' ').trim() : '';

        // 1. Product titel uit semantische heading of link
        let titel = '';
        const heading = card.querySelector(
            '[data-testid="product-block-product-name"], [data-testid="product-card-text-container"], [role="heading"]'
        );
        if (heading) {
            titel = cleanText(heading.getAttribute('title') || heading.innerText);
        }
        if (!titel && linkEl && linkEl.getAttribute('aria-label')) {
            titel = cleanText(linkEl.getAttribute('aria-label'));
        }
        if (!titel) continue;

        // 2. Actie / Promotie badge uit de DOM
        const nonPromoBadges = ['nieuw', 'new', 'tip', 'servicekostactie', 'combineer naar keuze'];
        const promos = [];
        const promoElements = card.querySelectorAll(
            '[data-testid="tag-promo-label"], [data-testid="product-card-promotion-label"], .ds-strap-line__label, [data-testid*="promo-label"]'
        );
        promoElements.forEach(p => {
            const val = cleanText(p.innerText || p.getAttribute('aria-label'));
            if (val && !nonPromoBadges.includes(val.toLowerCase()) && !promos.includes(val)) {
                promos.push(val);
            }
        });

        // 3. Stukprijs & Eenheidsprijs uit screenreader (.sr-only) of data-testid
        let stukprijs = '';
        let eenheid = '';

        // Check Delhaize / AH data-testids
        const priceEl = card.querySelector('[data-testid="product-block-price"], [data-testid="product-card-current-price"]');
        if (priceEl) {
            stukprijs = cleanText(priceEl.getAttribute('aria-label') || priceEl.innerText);
        }
        const descEl = card.querySelector('[data-testid="product-block-supplementary-price"], [data-testid="product-card-price-description"]');
        if (descEl) {
            eenheid = cleanText(descEl.getAttribute('aria-label') || descEl.innerText);
        }
        const unitPriceEl = card.querySelector('[data-testid="product-block-price-per-unit"]');
        if (unitPriceEl) {
            const up = cleanText(unitPriceEl.innerText || unitPriceEl.getAttribute('aria-label'));
            eenheid = eenheid ? `${eenheid} (${up})` : up;
        }

        // Check Colruyt .sr-only spans
        card.querySelectorAll('.sr-only').forEach(sr => {
            const txt = cleanText(sr.innerText);
            if (txt.toLowerCase().includes('per stuk')) {
                stukprijs = txt;
            } else if (txt.toLowerCase().includes('per liter') || txt.toLowerCase().includes('per kilogram')) {
                eenheid = txt;
            }
        });

        const contextLines = [
            promos.length > 0 ? `PROMOTIE_ACTIEF: ${promos.join(' | ')}` : `GEEN_PROMOTIE (standaardprijs)`,
            `titel: ${titel}`,
        ];
        if (stukprijs) contextLines.push(`stukprijs: ${stukprijs}`);
        if (eenheid) contextLines.push(`eenheid: ${eenheid}`);

        results.push({
            link: link,
            semantische_context: contextLines
        });
    }
    return results;
}"""

async def dismiss_cookie_banner(page):
    """Probeert automatisch bekende cookie banners weg te klikken."""
    cookie_selectors = [
        "#onetrust-accept-btn-handler",
        "button:has-text('Alles accepteren')",
        "button:has-text('Alle cookies accepteren')",
        "button:has-text('Alle cookies aanvaarden')",
        "button:has-text('Accepteren')",
        "button:has-text('Accepteer cookies')",
        "button:has-text('Accepteer')",
        "button:has-text('Akkoord')",
        "[data-testhook='cookie-accept-all']"
    ]
    for sel in cookie_selectors:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=800):
                print(f"  [Cookie-banner] Klikken op: '{sel}'")
                await btn.click()
                await page.wait_for_timeout(600)
                return True
        except Exception:
            pass
    return False

async def scroll_smoothly(page):
    """Scrollt omlaag zodat lazy-loaded productkaarten inladen."""
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
    print(f"\n[{store['naam']}] Zoeken naar '{query}' op: {url}")

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
        target_keywords = [
            query.lower(), "hipro", "danone", "barebells", "holie", "melkunie",
            "nakd", "nākd", "upfront", "protein", "proteïne", "eiwit", "reep", "bar"
        ]

        for card in cards:
            context_lines = card["semantische_context"]
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
                "supermarkt": store["naam"],
                "zoekterm": query,
                "link": link,
                "semantische_context": context_lines
            })

        print(f"  -> {len(found_items)} producten met rijke semantische context opgeslagen.")
        return found_items

    except Exception as e:
        print(f"  [FOUT] Kon {store['naam']} ({query}) niet verwerken: {e}")
        return []

async def extract_all_stores():
    print("Verbinden met Chrome op poort 9222...")
    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp("http://localhost:9222")
        except Exception as e:
            print(f"\n[FOUT] Kon niet verbinden met Chrome: {e}")
            print("Zorg dat je Chrome eerst opent via: ./start_browser.sh")
            return

        contexts = browser.contexts
        page = contexts[0].pages[0] if contexts and contexts[0].pages else await browser.new_page()

        alle_producten = []
        seen_links = set()

        queries = ["hipro", "barebells", "eiwitreep"] if "--quick" in sys.argv else MERKEN

        print(f"Start semantische extractie voor zoektermen: {queries}")

        for store in SUPERMARKTEN:
            for query in queries:
                items = await extract_page(page, store, query, seen_links)
                alle_producten.extend(items)
                await asyncio.sleep(1.0)

        with open("data.json", "w", encoding="utf-8") as f:
            json.dump(alle_producten, f, indent=2, ensure_ascii=False)

        print("\n=======================================================")
        print(f"[COMPLEET] Totaal {len(alle_producten)} producten met semantische context in data.json!")
        for store in SUPERMARKTEN:
            count = sum(1 for p in alle_producten if p["supermarkt"] == store["naam"])
            print(f"  - {store['naam']}: {count} producten")
        print("=======================================================")

if __name__ == "__main__":
    asyncio.run(extract_all_stores())
