import datetime
import hashlib
import json
import os
import re
import sys
import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "data.json")
SEEN_PROMOS_FILE = os.path.join(BASE_DIR, "seen_promos.json")
CACHE_FILE = os.path.join(BASE_DIR, "last_message.json")


def load_dotenv_file(dotenv_path=".env"):
    """Loads key-value pairs from .env into os.environ without external dependencies."""
    full_path = os.path.join(BASE_DIR, dotenv_path)
    if not os.path.exists(full_path):
        return
    try:
        with open(full_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                os.environ.setdefault(key, val)
    except Exception as e:
        print(f"[Warning] Failed to read .env: {e}")


load_dotenv_file()

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate")
MODEL = os.environ.get("OLLAMA_MODEL", "qwen3-coder:30b")


def notify_telegram(message):
    if not TOKEN or not CHAT_ID:
        print("❌ Error sending Telegram message: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing in .env / environment.")
        return False
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"},
            timeout=15
        )
        response.raise_for_status()
        print("✅ Telegram message delivered successfully!")
        return True
    except Exception as e:
        print(f"❌ Error sending Telegram message: {e}")
        return False


def load_seen_promos():
    """Loads the deal-level memory of active promotions."""
    if os.path.exists(SEEN_PROMOS_FILE):
        try:
            with open(SEEN_PROMOS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and "deals" in data and isinstance(data["deals"], dict):
                    return data["deals"]
        except Exception as e:
            print(f"[Warning] Could not read {SEEN_PROMOS_FILE}: {e}")
    return {}


def save_seen_promos(deals_dict):
    """Saves currently active promotions to seen_promos.json."""
    payload = {
        "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "active_deal_count": len(deals_dict),
        "deals": deals_dict
    }
    try:
        with open(SEEN_PROMOS_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[Warning] Could not save {SEEN_PROMOS_FILE}: {e}")


def save_cached_deal(message):
    msg_hash = hashlib.sha256(message.encode("utf-8")).hexdigest()
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "hash": msg_hash,
                "sent_at": datetime.datetime.now().isoformat(timespec="seconds"),
                "preview": message[:200]
            }, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[Warning] Could not save message cache: {e}")


FUTURE_PROMO_RE = re.compile(
    r"\b(vanaf\s+(maandag|dinsdag|woensdag|donderdag|vrijdag|zaterdag|zondag|\d{1,2}\s+(januari|februari|maart|april|mei|juni|juli|augustus|september|oktober|november|december|jan|feb|mrt|apr|jun|jul|aug|sep|okt|nov|dec)\b)|geldig\s+vanaf)\b",
    re.IGNORECASE
)


def is_at_least_50_percent_off(promotion_str):
    """
    Returns True only if the promotion gives at least 50% effective discount per item:
      - 1+1 gratis, 2e gratis, 2de gratis, 2+2 gratis, 1+2 gratis, etc.
      - Direct -50% (or higher, e.g. -60%, -70%), EXCLUDING '2de tegen -50%' / '2de aan -50%' (which is only 25% off).
    """
    p = (promotion_str or "").strip().lower()
    if not p:
        return False

    # Exclude '2nd at -50%' / '2nd half price' (only 25% effective discount)
    if re.search(r"\b(2de|2e|tweede)\b.*(-50%|halve\s+prijs|1/2\s+prijs)", p):
        return False

    # 1+1 free, 2nd free, 2+2 free, 1+2 free
    if re.search(r"\b(1\+1|2\+2|1\+2|2\+3|3\+3)\s*gratis\b", p) or re.search(r"\b(2e|2de|tweede)\s+gratis\b", p):
        return True

    # Direct percentage discount >= 50%
    for m in re.finditer(r"-\s*(\d+(?:[.,]\d+)?)\s*%|\b(\d+(?:[.,]\d+)?)\s*%\s*korting\b", p):
        pct_str = (m.group(1) or m.group(2)).replace(",", ".")
        try:
            if float(pct_str) >= 50.0:
                return True
        except ValueError:
            pass

    return False


def parse_semantic_context(context_lines, require_major_discount=True):
    """Extracts structured fields from a product's semantic_context list."""
    info = {
        "is_promo": False,
        "is_major_promo": False,
        "promotion": "",
        "title": "",
        "unit_price": "",
        "unit": ""
    }
    for line in context_lines:
        if line.startswith("PROMO_ACTIVE:"):
            info["is_promo"] = True
            info["promotion"] = line.split("PROMO_ACTIVE:", 1)[1].strip()
        elif line.startswith("title:"):
            info["title"] = line.split("title:", 1)[1].strip()
        elif line.startswith("unit_price:"):
            info["unit_price"] = line.split("unit_price:", 1)[1].strip()
        elif line.startswith("unit:"):
            info["unit"] = line.split("unit:", 1)[1].strip()

    # Ignore future promotions that are not yet active in-store (e.g., AH 'Vanaf maandag')
    if info["is_promo"] and (FUTURE_PROMO_RE.search(info["title"]) or FUTURE_PROMO_RE.search(info["promotion"])):
        info["is_promo"] = False
        info["promotion"] = ""

    if info["is_promo"]:
        info["is_major_promo"] = is_at_least_50_percent_off(info["promotion"])
        if require_major_discount and not info["is_major_promo"]:
            info["is_promo"] = False
            info["promotion"] = ""

    return info


def compute_deal_hash(supermarket, title, promotion, unit_price):
    """Computes a deterministic SHA-256 hash for an individual deal."""
    norm = lambda s: re.sub(r"\s+", " ", (s or "").strip().lower())
    raw_key = f"{norm(supermarket)}|{norm(title)}|{norm(promotion)}|{norm(unit_price)}"
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def evaluate_deals_memory(data, seen_promos):
    """
    Compares all current products in data.json against seen_promos.
    Returns:
      - enriched_data: copy of data with deal_status ('NEW_DEAL' or 'ONGOING_DEAL')
      - updated_seen_promos: dictionary containing only currently active deals
      - new_deals: list of newly discovered or further discounted deals
      - ongoing_deals: list of already known ongoing deals
    """
    now_iso = datetime.datetime.now().isoformat(timespec="seconds")
    scraped_stores = {
        item.get("supermarket")
        for item in data
        if item.get("supermarket")
    }

    updated_seen = {}
    # Preserve existing deals for stores that failed to scrape in this run
    for deal_hash, deal_obj in seen_promos.items():
        if deal_obj.get("supermarket") not in scraped_stores:
            updated_seen[deal_hash] = deal_obj

    new_deals = []
    ongoing_deals = []
    enriched_data = []

    for item in data:
        item_copy = dict(item)
        store = item.get("supermarket") or "Unknown"
        item_copy["supermarket"] = store

        raw_ctx = list(item.get("semantic_context") or [])
        parsed = parse_semantic_context(raw_ctx, require_major_discount=True)

        ctx = [
            f"PROMO_ACTIVE: {parsed['promotion']}" if parsed["is_promo"] else "NO_PROMO (standard price)",
            f"title: {parsed['title']}",
        ]
        if parsed["unit_price"]:
            ctx.append(f"unit_price: {parsed['unit_price']}")
        if parsed["unit"]:
            ctx.append(f"unit: {parsed['unit']}")

        if parsed["is_promo"]:
            deal_hash = compute_deal_hash(
                store, parsed["title"], parsed["promotion"], parsed["unit_price"]
            )
            is_ongoing = deal_hash in seen_promos
            status = "ONGOING_DEAL" if is_ongoing else "NEW_DEAL"
            first_seen = seen_promos[deal_hash].get("first_seen", now_iso) if is_ongoing else now_iso

            deal_record = {
                "supermarket": store,
                "title": parsed["title"],
                "promotion": parsed["promotion"],
                "unit_price": parsed["unit_price"],
                "unit": parsed["unit"],
                "link": item.get("link", ""),
                "first_seen": first_seen,
                "last_seen": now_iso
            }
            if is_ongoing:
                ongoing_deals.append(deal_record)
            else:
                new_deals.append(deal_record)

            updated_seen[deal_hash] = deal_record
            ctx.insert(1, f"deal_status: {status}")
            item_copy["deal_status"] = status

        item_copy["semantic_context"] = ctx
        enriched_data.append(item_copy)

    return enriched_data, updated_seen, new_deals, ongoing_deals


def sanitize_telegram_message(text):
    """Ensures valid Telegram Markdown (single * for bold, no ### headers)."""
    text = re.sub(r'\*\*(.+?)\*\*', r'*\1*', text)

    lines = []
    for line in text.splitlines():
        trimmed = line.strip()
        header_match = re.match(r'^#{1,6}\s*(.*)', trimmed)
        if header_match:
            content = header_match.group(1).replace('*', '').strip()
            lines.append(f"\n*{content}*")
        else:
            if "🆕" in line:
                line = re.sub(r'\s*_?\(still running\)_?', '', line, flags=re.IGNORECASE)
            lines.append(line)

    return "\n".join(lines).strip()


def call_ollama(prompt):
    response = requests.post(OLLAMA_URL, json={
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "num_ctx": 16384,
            "temperature": 0.0
        }
    }, timeout=180)
    response.raise_for_status()
    raw = response.json().get("response", "").strip()
    return re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()


def analyze_deals(enriched_data):
    # Group by supermarket so the LLM can inspect each store with 100% focused attention
    stores = {}
    for item in enriched_data:
        s = item.get("supermarket", "Unknown")
        stores.setdefault(s, []).append(item)

    store_promo_extracts = {}

    for store_name, items in stores.items():
        print(f"[Step 1 - Extraction] Ollama is analyzing {len(items)} products from {store_name}...")
        lines = []
        for idx, d in enumerate(items, 1):
            ctx_str = " || ".join(d.get("semantic_context", []))
            lines.append(f"Item {idx}: {ctx_str}")
        store_block = "\n".join(lines)

        extract_prompt = f"""Below are all {len(items)} scraped protein products from {store_name}:

{store_block}

TASK:
Find ONLY the lines in the {store_name} list above that start with `PROMO_ACTIVE:` AND offer **at least 50% effective discount per item** (such as `1+1 gratis`, `2e gratis`, `2+2 gratis`, `1+2 gratis`, or `-50%` and higher).
- Completely ignore every line that says `NO_PROMO (standard price)`!
- Completely ignore minor discounts under 50% off (such as `-10%`, `-20%`, `-25%`, `-33%`, or `2de tegen -50%` which is only 25% off)!
- For each qualifying `PROMO_ACTIVE:` line found, copy the exact `deal_status` (`NEW_DEAL` or `ONGOING_DEAL`), `title`, promotion, and `unit_price` from that same line.
- If {store_name} has zero qualifying lines with >= 50% discount, reply ONLY with: "NO_PROMOS".
Return only the extracted list without any introduction."""

        try:
            store_promo_extracts[store_name] = call_ollama(extract_prompt)
        except Exception as e:
            print(f"Error during Ollama extraction for {store_name}: {e}")
            return None

    # Step 2: Synthesis & Price Calculation by Ollama
    print("[Step 2 - Comparison & Formatting] Ollama is calculating deals and formatting the Telegram alert...")
    combined_extracts = "\n\n".join(
        f"=== {store} ===\n{ext}" for store, ext in store_promo_extracts.items()
    )

    final_prompt = f"""You are a smart supermarket promo analyst for an athlete in Dendermonde (Belgium).
From the full product database of Albert Heijn, Colruyt, and Delhaize, the following active promotions were extracted in Step 1:

{combined_extracts}

YOUR TASK:
Filter strictly for **major deals (at least 50% effective discount per item)**, calculate the effective deal prices accurately, and write a concise final Telegram message in ENGLISH:

1. STRICT >= 50% DISCOUNT FILTER & UNIT PRICE CALCULATION:
   - ONLY include promotions that give **at least 50% effective discount per item** (`1+1 gratis`, `2e gratis`, `2+2 gratis`, `1+2 gratis`, or direct `-50%` and higher).
   - EXCLUDE any minor discounts under 50% off (do NOT include `-10%`, `-20%`, `-25%`, or `2de tegen -50%`!).
   - The `unit_price` listed is ALWAYS the regular standard price per item before discount (note: Belgian sites may write `2 euro 09 cent` or `€ 2,09`, which means €2.09).
   - For `1+1 gratis` or `2e gratis` (1+1 free / 2nd free): you get 2 items for the price of 1 (= 50% discount per item, so `unit_price * 0.50`).
     * Example: €2.09 per item with 1+1 gratis ➔ `2.09 * 0.50` = *€1.05/pc* when buying 2 (regular €2.09).
     * Example: €2.49 per item with 2e gratis ➔ `2.49 * 0.50` = *€1.25/pc* when buying 2 (regular €2.49).
   - Translate Dutch promo labels into clean English (`1+1 free`, `2nd free`, `-50%`).

2. GROUP FLAVORS AND VARIANTS OF THE SAME BRAND ON A SINGLE LINE (CRITICAL):
   - When a brand at the same store has **multiple** flavors, sizes, or variants on promo (e.g., multiple flavors of *XXL Nutrition Fitpudding* or *Arla Protein Pudding*), ALWAYS merge them into **one single bullet point per brand/product group** with `(various flavors)` or the specific variants!
   - When a brand at a store has only **1 flavor/variant** on promo, put that specific flavor in parentheses (and NOT `various flavors`), e.g. `(Chocolate 200g)` or `(Strawberry & Raspberry)`.
   - Use a price range if prices vary slightly across variants.
   - Desired grouping examples:
     * `• 🆕 *Arla Protein Pudding* (various flavors) – 1+1 free ➔ *€1.05/pc* (regular €2.09)`
     * `• 🆕 *XXL Nutrition Fitmousse* (Chocolate) – 2nd free ➔ *€1.25/pc* (regular €2.49)`
     * `• *Holie's Chewy Bar* (various flavors) – 1+1 free ➔ *€1.75 - €1.90/pc* (regular €3.49 - €3.79) (still running)`

3. MARKING NEW VS. ONGOING DEALS (STRICTLY EITHER/OR, NEVER BOTH):
   - Include ALL qualifying (>= 50% off) promotions found in Step 1.
   - Each promotion from Step 1 has `deal_status: NEW_DEAL` or `deal_status: ONGOING_DEAL`.
   - Case A (`NEW_DEAL`): If a product group (or at least one variant within it) has `NEW_DEAL`, place `🆕 ` right after the bullet `• ` and **NEVER** put `(still running)` at the end of that line!
   - Case B (`ONGOING_DEAL`): If a product group consists exclusively of `ONGOING_DEAL`, do **NOT** put `🆕` in front, and append `(still running)` at the very end of the line.
   - A line must NEVER contain both `🆕` and `(still running)`!

4. STRUCTURE & TELEGRAM FORMATTING (STRICT):
   - Start with the header: `🥊 *Protein Promo Alert Dendermonde (50%+ Off)* 🥊`
   - Use store headings: `🛒 *Delhaize*`, `🛒 *Colruyt*`, `🛒 *Albert Heijn*`.
   - If a store has `NO_PROMOS` (no deals with >= 50% discount), write underneath: `• No 50%+ promos this week.`
   - For bold text use ONLY single asterisks: `*bold*` (NEVER double `**` and NEVER `#` headers!).
   - Use `•` for bullet points.
   - Conclude with a brief `💡 *Advice:*` of 1-2 sentences in English highlighting the best deals.
   - Output ONLY the Telegram message.
"""

    try:
        raw_message = call_ollama(final_prompt)
        return sanitize_telegram_message(raw_message)
    except Exception as e:
        print(f"Error during Ollama final analysis: {e}")
        return None


if __name__ == "__main__":
    force_send = "--force" in sys.argv
    dry_run = "--dry-run" in sys.argv

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
    except FileNotFoundError:
        print("No data.json found. Run extract_supermarkets.py first.")
        sys.exit(0)

    if not raw_data:
        print("data.json is empty.")
        sys.exit(0)

    seen_promos = load_seen_promos()
    enriched_data, updated_seen, new_deals, ongoing_deals = evaluate_deals_memory(raw_data, seen_promos)

    print(
        f"📊 Deal memory check ({SEEN_PROMOS_FILE}): "
        f"{len(new_deals)} new/changed deal(s), {len(ongoing_deals)} ongoing deal(s)."
    )
    for nd in new_deals:
        print(f"   🆕 [{nd['supermarket']}] {nd['title']} -> {nd['promotion']} ({nd['unit_price']})")
    for od in ongoing_deals:
        print(f"   ⏳ [{od['supermarket']}] {od['title']} -> {od['promotion']} ({od['unit_price']})")

    if not new_deals and not ongoing_deals and not force_send and not dry_run:
        save_seen_promos(updated_seen)
        print("ℹ️ No active promotions found across any supermarket. No message sent.")
        sys.exit(0)

    if not new_deals and not force_send and not dry_run:
        # Still update seen_promos.json so expired promotions are pruned from memory
        save_seen_promos(updated_seen)
        print("🛡️ Smart Anti-Spam active: No new or further discounted deals found.")
        print(f"   All {len(ongoing_deals)} active deals are still running and were already notified.")
        print("   (Use '--force' to send an overview anyway or '--dry-run' to test).")
        sys.exit(0)

    draft_message = analyze_deals(enriched_data)
    if not draft_message:
        print("No message generated.")
        sys.exit(0)

    print("\n--- TELEGRAM MESSAGE GENERATED BY OLLAMA ---")
    print(draft_message)
    print("--------------------------------------------\n")

    if dry_run:
        print(f"[DRY-RUN] Message not sent to Telegram and {SEEN_PROMOS_FILE} not overwritten.")
        sys.exit(0)

    print("Sending to Telegram...")
    success = notify_telegram(draft_message)
    if success:
        save_seen_promos(updated_seen)
        save_cached_deal(draft_message)
        print(f"💾 Updated {SEEN_PROMOS_FILE} with {len(updated_seen)} active deals.")
