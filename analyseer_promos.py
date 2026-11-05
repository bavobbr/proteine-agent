import datetime
import hashlib
import json
import os
import re
import sys
import requests

def load_dotenv_file(dotenv_path=".env"):
    """Laadt sleutel-waardeparen uit .env in os.environ zonder externe afhankelijkheden."""
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
        print(f"[Waarschuwing] Kon .env niet inlezen: {e}")

load_dotenv_file()

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
SEEN_PROMOS_FILE = "seen_promos.json"
CACHE_FILE = "laatste_bericht.json"
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate")
MODEL = os.environ.get("OLLAMA_MODEL", "qwen3-coder:30b")

def notify_telegram(message):
    if not TOKEN or not CHAT_ID:
        print("❌ Fout bij verzenden Telegram: TELEGRAM_BOT_TOKEN of TELEGRAM_CHAT_ID ontbreekt in .env / environment.")
        return False
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"},
            timeout=15
        )
        response.raise_for_status()
        print("✅ Telegram bericht succesvol afgeleverd!")
        return True
    except Exception as e:
        print(f"❌ Fout bij verzenden Telegram: {e}")
        return False

def load_seen_promos():
    """Laadt het geheugen van actieve promoties op deal-niveau."""
    if os.path.exists(SEEN_PROMOS_FILE):
        try:
            with open(SEEN_PROMOS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and "deals" in data and isinstance(data["deals"], dict):
                    return data["deals"]
        except Exception as e:
            print(f"[Waarschuwing] Kon {SEEN_PROMOS_FILE} niet lezen: {e}")
    return {}

def save_seen_promos(deals_dict):
    """Slaat de huidige actieve promoties op in seen_promos.json."""
    payload = {
        "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "active_deal_count": len(deals_dict),
        "deals": deals_dict
    }
    try:
        with open(SEEN_PROMOS_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[Waarschuwing] Kon {SEEN_PROMOS_FILE} niet opslaan: {e}")

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
        print(f"[Waarschuwing] Kon cache niet opslaan: {e}")

def parse_semantic_context(context_lines):
    """Haalt gestructureerde velden uit semantische_context van een product."""
    info = {
        "is_promo": False,
        "promotie": "",
        "titel": "",
        "stukprijs": "",
        "eenheid": ""
    }
    for line in context_lines:
        if line.startswith("PROMOTIE_ACTIEF:"):
            info["is_promo"] = True
            info["promotie"] = line.split("PROMOTIE_ACTIEF:", 1)[1].strip()
        elif line.startswith("titel:"):
            info["titel"] = line.split("titel:", 1)[1].strip()
        elif line.startswith("stukprijs:"):
            info["stukprijs"] = line.split("stukprijs:", 1)[1].strip()
        elif line.startswith("eenheid:"):
            info["eenheid"] = line.split("eenheid:", 1)[1].strip()
    return info

def compute_deal_hash(supermarkt, titel, promotie, stukprijs):
    """Berekent een deterministische SHA-256 hash voor één specifieke deal."""
    norm = lambda s: re.sub(r"\s+", " ", (s or "").strip().lower())
    raw_key = f"{norm(supermarkt)}|{norm(titel)}|{norm(promotie)}|{norm(stukprijs)}"
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

def evaluate_deals_memory(data, seen_promos):
    """
    Vergelijkt alle huidige producten in data.json met seen_promos.
    Geeft terug:
      - enriched_data: kopie van data met deal_status ('NIEUWE_DEAL' of 'LOPENDE_DEAL')
      - updated_seen_promos: nieuwe dictionary met enkel nog de actieve deals
      - new_deals: lijst van nieuw ontdekte of gewijzigde deals
      - ongoing_deals: lijst van reeds bekende lopende deals
    """
    now_iso = datetime.datetime.now().isoformat(timespec="seconds")
    scraped_stores = {item.get("supermarkt") for item in data if item.get("supermarkt")}

    updated_seen = {}
    # Bewaar bestaande deals van winkels die in deze run eventueel niet gescraped konden worden
    for deal_hash, deal_obj in seen_promos.items():
        if deal_obj.get("supermarkt") not in scraped_stores:
            updated_seen[deal_hash] = deal_obj

    new_deals = []
    ongoing_deals = []
    enriched_data = []

    for item in data:
        item_copy = dict(item)
        ctx = list(item.get("semantische_context", []))
        parsed = parse_semantic_context(ctx)

        if parsed["is_promo"]:
            store = item.get("supermarkt", "Onbekend")
            deal_hash = compute_deal_hash(
                store, parsed["titel"], parsed["promotie"], parsed["stukprijs"]
            )
            if deal_hash in seen_promos:
                status = "LOPENDE_DEAL"
                prev = seen_promos[deal_hash]
                deal_record = {
                    "supermarkt": store,
                    "titel": parsed["titel"],
                    "promotie": parsed["promotie"],
                    "stukprijs": parsed["stukprijs"],
                    "eenheid": parsed["eenheid"],
                    "link": item.get("link", ""),
                    "first_seen": prev.get("first_seen", now_iso),
                    "last_seen": now_iso
                }
                ongoing_deals.append(deal_record)
            else:
                status = "NIEUWE_DEAL"
                deal_record = {
                    "supermarkt": store,
                    "titel": parsed["titel"],
                    "promotie": parsed["promotie"],
                    "stukprijs": parsed["stukprijs"],
                    "eenheid": parsed["eenheid"],
                    "link": item.get("link", ""),
                    "first_seen": now_iso,
                    "last_seen": now_iso
                }
                new_deals.append(deal_record)

            updated_seen[deal_hash] = deal_record
            # Voeg deal_status direct na de PROMOTIE_ACTIEF tag toe voor Ollama
            ctx.insert(1, f"deal_status: {status}")
            item_copy["deal_status"] = status

        item_copy["semantische_context"] = ctx
        enriched_data.append(item_copy)

    return enriched_data, updated_seen, new_deals, ongoing_deals

def sanitize_telegram_message(text):
    """Zorgt voor foutloze Telegram Markdown (enkele * voor vet, geen ### headers)."""
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
                line = re.sub(r'\s*_?\(loopt nog\)_?', '', line)
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
    # Groepeer per supermarkt zodat het LLM elke winkel met 100% scherpe aandacht kan lezen
    stores = {}
    for item in enriched_data:
        s = item.get("supermarkt", "Onbekend")
        stores.setdefault(s, []).append(item)

    store_Promo_extracts = {}

    for store_name, items in stores.items():
        print(f"[Stap 1 - Extractie] Ollama analyseert {len(items)} producten van {store_name}...")
        lines = []
        for idx, d in enumerate(items, 1):
            ctx_str = " || ".join(d.get("semantische_context", []))
            lines.append(f"Item {idx}: {ctx_str}")
        store_block = "\n".join(lines)

        extract_prompt = f"""Hieronder staan alle {len(items)} gescrapete eiwitproducten van {store_name}:

{store_block}

OPDRACHT:
Zoek in bovenstaande lijst van {store_name} UITSLUITEND de regels die beginnen met `PROMOTIE_ACTIEF:`.
- Negeer elke regel waar `GEEN_PROMOTIE (standaardprijs)` staat volledig!
- Neem voor elke gevonden `PROMOTIE_ACTIEF:` regel exact de `deal_status` (`NIEUWE_DEAL` of `LOPENDE_DEAL`), de `titel`, de promotie en de `stukprijs` van diezelfde regel over.
- Als er voor {store_name} geen enkele regel met `PROMOTIE_ACTIEF:` is, antwoord dan uitsluitend met: "GEEN_ACTIES".
Geef alleen de gevonden lijst terug zonder inleiding."""

        try:
            store_Promo_extracts[store_name] = call_ollama(extract_prompt)
        except Exception as e:
            print(f"Fout bij Ollama extractie voor {store_name}: {e}")
            return None

    # Stap 2: Synthese & Berekening door Ollama
    print("[Stap 2 - Vergelijking & Opmaak] Ollama berekent de deals en stelt het Telegram-bericht op...")
    combined_extracts = "\n\n".join(
        f"=== {store} ===\n{ext}" for store, ext in store_Promo_extracts.items()
    )

    final_prompt = f"""Je bent een slimme promo-analist voor een sporter in Dendermonde (België).
Uit de volledige productendatabase van Albert Heijn, Colruyt en Delhaize zijn in Stap 1 de volgende actieve promoties geëxtraheerd:

{combined_extracts}

JOUW OPDRACHT:
Reken de acties hierboven nauwkeurig door en schrijf het definitieve Telegram-bericht:

1. BEREKENING VAN DE ACTIEPRIJS PER STUK:
   - De vermelde `stukprijs` in de lijst is ALTIJD de normale standaardprijs per stuk vóór korting.
   - Bij `1+1 gratis`: je krijgt 2 stuks voor de prijs van 1 (= 50% korting per stuk, dus `stukprijs * 0.50`).
     * Voorbeeld: €2,09 per stuk met 1+1 gratis ➔ `2,09 * 0.50` = *€1,05/st* bij aankoop van 2 (normaal €2,09).
     * Voorbeeld: €2,15 per stuk met 1+1 gratis ➔ `2,15 * 0.50` = *€1,08/st* bij aankoop van 2 (normaal €2,15).
   - Bij `2de tegen -50%`: je koopt 2 stuks voor 1.5x de stukprijs (= 25% korting per stuk, dus `stukprijs * 0.75`).
     * Voorbeeld: €2,35 per stuk met 2de tegen -50% ➔ `2,35 * 0.75` = *€1,76/st* bij aankoop van 2 (normaal €2,35).
     * Voorbeeld: €2,49 per stuk met 2de tegen -50% ➔ `2,49 * 0.75` = *€1,87/st* bij aankoop van 2 (normaal €2,49).
     * Voorbeeld: €4,05 per stuk met 2de tegen -50% ➔ `4,05 * 0.75` = *€3,04/st* bij aankoop van 2 (normaal €4,05).
     * Voorbeeld: €2,55 per stuk met 2de tegen -50% ➔ `2,55 * 0.75` = *€1,91/st* bij aankoop van 2 (normaal €2,55).
   - Bij `-25% vanaf 2 st`: vermenigvuldig de stukprijs met `0.75` (bijv. €1,99 * 0.75 = *€1,49/st* vanaf 2 stuks).
   - Bij `-10% vanaf 4 st`: vermenigvuldig de stukprijs met `0.90` (bijv. €3,90 * 0.90 = *€3,51/st* vanaf 4 stuks).
   - Bij `€ X,XX/st vanaf 2 st`: vermeld die actieprijs én de normale stukprijs (bijv. *€1,69/st* vanaf 2 stuks, normaal €2,25).

2. GROEPEER SMAKEN EN VARIANTEN VAN HETZELFDE MERK OP ÉÉN REGEL (CRUCIAAL):
   - Als een merk bij dezelfde winkel **meerdere** smaken, formaten of varianten in actie heeft (bijv. 3 smaken *NXT Level Eiwitrepen*, 3 smaken *Isostar Bars* bij Colruyt, 2 smaken *Joyfuel Bars*, 2 varianten *Philadelphia Protein*, of 2 formaten *Chocomel Proteïne*), voeg deze dan ALTIJD samen tot **één enkele bulletpoint per merk/productgroep** met `(div. smaken)` of de varianten!
   - Als er van een merk bij een winkel maar **1 smaak/variant** in actie is, vermeld dan die specifieke smaak tussen haakjes (en NIET `div. smaken`), bijv. `(Vanille 330ml)` of `(Aardbei)`.
   - Gebruik een prijsrange of "vanaf"-prijs als de prijzen tussen varianten licht verschillen.
   - Voorbeelden van gewenste groepering:
     * `• 🆕 *NXT Level Eiwitrepen* (div. smaken) – 2de tegen -50% ➔ *€1,76 - €1,87/st* (normaal €2,35 - €2,49)`
     * `• 🆕 *Joyfuel Protein Bars* (div. smaken) – -25% vanaf 2 st ➔ *€2,32/st* (normaal €3,09)`
     * `• 🆕 *Philadelphia Protein* (Cottage cheese & Spread) – -25% vanaf 2 st ➔ *€1,49 - €2,84/st* (normaal €1,99 - €3,79)`
     * `• 🆕 *HiPRO Drinkyoghurt* (Vanille 330ml) – -10% vanaf 4 st ➔ *€3,51/st* (normaal €3,90)`
     * `• *Barebells Protein Bar* (div. smaken) – 2de tegen -50% ➔ *€1,87/st* (normaal €2,49) (loopt nog)`

3. NIEUWE VS. LOPENDE DEALS MARKEREN (STRIKT OF/OF, NOOIT BEIDE):
   - Neem ALLE gevonden promoties uit Stap 1 op in het overzicht (laat geen enkel merk weg!).
   - Elke promotie uit Stap 1 heeft `deal_status: NIEUWE_DEAL` of `deal_status: LOPENDE_DEAL`.
   - Geval A (`NIEUWE_DEAL`): Als een productgroep (of minstens één variant daarbinnen) `NIEUWE_DEAL` is, zet dan `🆕 ` direct na het bulletpoint `• ` en zet **NOOIT** `(loopt nog)` achteraan die regel!
   - Geval B (`LOPENDE_DEAL`): Als een productgroep uitsluitend uit `LOPENDE_DEAL` bestaat, zet dan **GEEN** `🆕` vooraan, maar zet helemaal achteraan de regel `(loopt nog)`.
   - Een regel mag dus NOOIT tegelijk `🆕` én `(loopt nog)` bevatten!

4. STRUCTUUR & TELEGRAM OPMAAK (STRIKT):
   - Begin met de titel: `🥊 *Eiwit Promo Alert Dendermonde* 🥊`
   - Gebruik per winkel de kopjes: `🛒 *Delhaize*`, `🛒 *Colruyt*`, `🛒 *Albert Heijn*`.
   - Als een winkel `GEEN_ACTIES` heeft, zet daar dan onder: `• Geen acties deze week (alles op standaardprijs).`
   - Gebruik voor vetgedrukte tekst UITSLUITEND enkele sterretjes: `*vet*` (NOOIT dubbele `**` en NOOIT `#` headers!).
   - Gebruik `•` voor bulletpoints.
   - Sluit af met een kort `💡 *Advies:*` van 1-2 zinnen waarin je vooral focust op de nieuwe deals (`🆕`) en de scherpste prijzen.
   - Geef UITSLUITEND het Telegram-bericht terug.
"""

    try:
        ruw_bericht = call_ollama(final_prompt)
        return sanitize_telegram_message(ruw_bericht)
    except Exception as e:
        print(f"Fout bij Ollama eindanalyse: {e}")
        return None

if __name__ == "__main__":
    force_send = "--force" in sys.argv
    dry_run = "--dry-run" in sys.argv

    try:
        with open("data.json", "r", encoding="utf-8") as f:
            raw_data = json.load(f)
    except FileNotFoundError:
        print("Geen data.json gevonden. Draai eerst extract_supermarkten.py.")
        sys.exit(0)

    if not raw_data:
        print("data.json is leeg.")
        sys.exit(0)

    seen_promos = load_seen_promos()
    enriched_data, updated_seen, new_deals, ongoing_deals = evaluate_deals_memory(raw_data, seen_promos)

    print(
        f"📊 Deal-geheugen check ({SEEN_PROMOS_FILE}): "
        f"{len(new_deals)} nieuwe/gewijzigde deal(s), {len(ongoing_deals)} reeds lopende deal(s)."
    )
    for nd in new_deals:
        print(f"   🆕 [{nd['supermarkt']}] {nd['titel']} -> {nd['promotie']} ({nd['stukprijs']})")
    for od in ongoing_deals:
        print(f"   ⏳ [{od['supermarkt']}] {od['titel']} -> {od['promotie']} ({od['stukprijs']})")

    if not new_deals and not ongoing_deals and not force_send and not dry_run:
        save_seen_promos(updated_seen)
        print("ℹ️ Geen enkele actieve promotie gevonden bij de supermarkten. Geen bericht verzonden.")
        sys.exit(0)

    if not new_deals and not force_send and not dry_run:
        # Werk wel seen_promos.json bij (zodat afgelopen acties uit het geheugen verdwijnen)
        save_seen_promos(updated_seen)
        print("🛡️ Slimme Anti-Spam actief: Geen nieuwe of verder afgeprijsde deals gevonden.")
        print(f"   Alle {len(ongoing_deals)} actieve deals lopen nog door en zijn al eerder gemeld.")
        print("   (Gebruik '--force' om toch een overzicht te sturen of '--dry-run' om te testen).")
        sys.exit(0)

    concept_bericht = analyze_deals(enriched_data)
    if not concept_bericht:
        print("Geen bericht gegenereerd.")
        sys.exit(0)

    print("\n--- TELEGRAM BERICHT DOOR OLLAMA ---")
    print(concept_bericht)
    print("------------------------------------\n")

    if dry_run:
        print(f"[DRY-RUN] Bericht niet naar Telegram verzonden en {SEEN_PROMOS_FILE} niet overschreven.")
        sys.exit(0)

    print("Versturen naar Telegram...")
    succes = notify_telegram(concept_bericht)
    if succes:
        save_seen_promos(updated_seen)
        save_cached_deal(concept_bericht)
        print(f"💾 {SEEN_PROMOS_FILE} bijgewerkt met {len(updated_seen)} actieve deals.")
