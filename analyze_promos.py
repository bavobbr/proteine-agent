import datetime
import hashlib
import json
import os
import re
import sys
import requests


def load_dotenv_file(dotenv_path=".env"):
    """Loads key-value pairs from .env into os.environ without external dependencies."""
    full_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), dotenv_path)
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
SEEN_PROMOS_FILE = "seen_promos.json"
CACHE_FILE = "last_message.json"
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


def parse_semantic_context(context_lines):
    """Extracts structured fields from a product's semantic_context list."""
    info = {
        "is_promo": False,
        "promotion": "",
        "title": "",
        "unit_price": "",
        "unit": ""
    }
    for line in context_lines:
        if line.startswith("PROMO_ACTIVE:"):
            info["is_promo"] = True
            info["promotion"] = line.split("PROMO_ACTIVE:", 1)[1].strip()
        elif line.startswith("PROMOTIE_ACTIEF:"):
            info["is_promo"] = True
            info["promotion"] = line.split("PROMOTIE_ACTIEF:", 1)[1].strip()
        elif line.startswith("title:"):
            info["title"] = line.split("title:", 1)[1].strip()
        elif line.startswith("titel:"):
            info["title"] = line.split("titel:", 1)[1].strip()
        elif line.startswith("unit_price:"):
            info["unit_price"] = line.split("unit_price:", 1)[1].strip()
        elif line.startswith("stukprijs:"):
            info["unit_price"] = line.split("stukprijs:", 1)[1].strip()
        elif line.startswith("unit:"):
            info["unit"] = line.split("unit:", 1)[1].strip()
        elif line.startswith("eenheid:"):
            info["unit"] = line.split("eenheid:", 1)[1].strip()
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
        (item.get("supermarket") or item.get("supermarkt"))
        for item in data
        if (item.get("supermarket") or item.get("supermarkt"))
    }

    updated_seen = {}
    # Preserve existing deals for stores that failed to scrape in this run
    for deal_hash, deal_obj in seen_promos.items():
        store_key = deal_obj.get("supermarket") or deal_obj.get("supermarkt")
        if store_key not in scraped_stores:
            updated_seen[deal_hash] = deal_obj

    new_deals = []
    ongoing_deals = []
    enriched_data = []

    for item in data:
        item_copy = dict(item)
        store = item.get("supermarket") or item.get("supermarkt") or "Unknown"
        item_copy["supermarket"] = store

        raw_ctx = list(item.get("semantic_context") or item.get("semantische_context") or [])
        parsed = parse_semantic_context(raw_ctx)

        # Normalize context lines to English keys
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
            if deal_hash in seen_promos:
                status = "ONGOING_DEAL"
                prev = seen_promos[deal_hash]
                deal_record = {
                    "supermarket": store,
                    "title": parsed["title"],
                    "promotion": parsed["promotion"],
                    "unit_price": parsed["unit_price"],
                    "unit": parsed["unit"],
                    "link": item.get("link", ""),
                    "first_seen": prev.get("first_seen", now_iso),
                    "last_seen": now_iso
                }
                ongoing_deals.append(deal_record)
            else:
                status = "NEW_DEAL"
                deal_record = {
                    "supermarket": store,
                    "title": parsed["title"],
                    "promotion": parsed["promotion"],
                    "unit_price": parsed["unit_price"],
                    "unit": parsed["unit"],
                    "link": item.get("link", ""),
                    "first_seen": now_iso,
                    "last_seen": now_iso
                }
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
                line = re.sub(r'\s*_?\((?:still running|loopt nog)\)_?', '', line, flags=re.IGNORECASE)
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
Find ONLY the lines in the {store_name} list above that start with `PROMO_ACTIVE:`.
- Completely ignore every line that says `NO_PROMO (standard price)`!
- For each `PROMO_ACTIVE:` line found, copy the exact `deal_status` (`NEW_DEAL` or `ONGOING_DEAL`), `title`, promotion, and `unit_price` from that same line.
- If {store_name} has zero lines with `PROMO_ACTIVE:`, reply ONLY with: "NO_PROMOS".
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
Calculate the effective deal prices accurately and write the final Telegram message in ENGLISH:

1. EFFECTIVE PROMO UNIT PRICE CALCULATION:
   - The `unit_price` listed is ALWAYS the regular standard price per item before discount (note: Belgian sites may write `2 euro 09 cent` or `€ 2,09`, which means €2.09).
   - For `1+1 gratis` (1+1 free): you get 2 items for the price of 1 (= 50% discount per item, so `unit_price * 0.50`).
     * Example: €2.09 per item with 1+1 gratis ➔ `2.09 * 0.50` = *€1.05/pc* when buying 2 (regular €2.09).
     * Example: €2.15 per item with 1+1 gratis ➔ `2.15 * 0.50` = *€1.08/pc* when buying 2 (regular €2.15).
   - For `2de tegen -50%` (2nd at -50%): you buy 2 items for 1.5x the unit price (= 25% discount per item, so `unit_price * 0.75`).
     * Example: €2.35 per item with 2nd at -50% ➔ `2.35 * 0.75` = *€1.76/pc* when buying 2 (regular €2.35).
     * Example: €2.49 per item with 2nd at -50% ➔ `2.49 * 0.75` = *€1.87/pc* when buying 2 (regular €2.49).
   - For `-25% vanaf 2 st` (-25% from 2 pcs): multiply unit_price by `0.75` (e.g. €1.99 * 0.75 = *€1.49/pc* from 2 pcs).
   - For `-10% vanaf 4 st` (-10% from 4 pcs): multiply unit_price by `0.90` (e.g. €3.90 * 0.90 = *€3.51/pc* from 4 pcs).
   - Translate Dutch promo labels into clean English (e.g., `1+1 free`, `2nd at -50%`, `-25% from 2 pcs`, `-10% from 4 pcs`).

2. GROUP FLAVORS AND VARIANTS OF THE SAME BRAND ON A SINGLE LINE (CRITICAL):
   - When a brand at the same store has **multiple** flavors, sizes, or variants on promo (e.g., 2 flavors of *Joyfuel Bars*, 2 variants of *Philadelphia Protein*, or 2 flavors of *Arla Protein Pudding*), ALWAYS merge them into **one single bullet point per brand/product group** with `(various flavors)` or the specific variants!
   - When a brand at a store has only **1 flavor/variant** on promo, put that specific flavor in parentheses (and NOT `various flavors`), e.g. `(Vanilla 330ml)` or `(Strawberry)`.
   - Use a price range if prices vary slightly across variants.
   - Desired grouping examples:
     * `• 🆕 *NXT Level Protein Bars* (various flavors) – 2nd at -50% ➔ *€1.76 - €1.87/pc* (regular €2.35 - €2.49)`
     * `• 🆕 *Joyfuel Protein Bars* (various flavors) – -25% from 2 pcs ➔ *€2.32/pc* (regular €3.09)`
     * `• 🆕 *Philadelphia Protein* (Cottage cheese & Spread) – -25% from 2 pcs ➔ *€1.49 - €2.84/pc* (regular €1.99 - €3.79)`
     * `• 🆕 *HiPRO Drink Yogurt* (Vanilla 330ml) – -10% from 4 pcs ➔ *€3.51/pc* (regular €3.90)`
     * `• *Barebells Protein Bar* (various flavors) – 2nd at -50% ➔ *€1.87/pc* (regular €2.49) (still running)`

3. MARKING NEW VS. ONGOING DEALS (STRICTLY EITHER/OR, NEVER BOTH):
   - Include ALL promotions found in Step 1 (do not omit any brand!).
   - Each promotion from Step 1 has `deal_status: NEW_DEAL` or `deal_status: ONGOING_DEAL`.
   - Case A (`NEW_DEAL`): If a product group (or at least one variant within it) has `NEW_DEAL`, place `🆕 ` right after the bullet `• ` and **NEVER** put `(still running)` at the end of that line!
   - Case B (`ONGOING_DEAL`): If a product group consists exclusively of `ONGOING_DEAL`, do **NOT** put `🆕` in front, and append `(still running)` at the very end of the line.
   - A line must NEVER contain both `🆕` and `(still running)`!

4. STRUCTURE & TELEGRAM FORMATTING (STRICT):
   - Start with the header: `🥊 *Protein Promo Alert Dendermonde* 🥊`
   - Use store headings: `🛒 *Delhaize*`, `🛒 *Colruyt*`, `🛒 *Albert Heijn*`.
   - If a store has `NO_PROMOS`, write underneath: `• No promos this week (everything at standard price).`
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
        with open("data.json", "r", encoding="utf-8") as f:
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
