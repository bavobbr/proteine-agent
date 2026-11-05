# Project Context: Lokale AI Promo-Agent (Dendermonde)

## 🎯 De Usecase
Bavo (45) en zijn zoon Mauro (17) sporten veel (veldhockey, fitness, core stability) en consumeren eiwitrijke repen en dranken. Deze producten (zoals HiPRO, Barebells, Holie's, Upfront) zijn standaard vrij duur (€1,50 - €3,00 per stuk). In Dendermonde (België) zijn er regelmatig 1+1, 2de aan -50% of volumekortingen bij lokale supermarkten (Albert Heijn, Colruyt, Delhaize).

**Het Doel:** Een 100% lokale, autonome AI-agent draaien op Ubuntu 26.04 die wekelijks deze supermarkten onzichtbaar scrapet, de prijzen en promo's analyseert met een lokaal LLM (zonder fragiele hardcoded Python-filters), en Bavo via Telegram waarschuwt met een overzichtelijk en gegroepeerd promo-overzicht.

## 🛠️ De Architectuur & Tech Stack
* **OS:** Ubuntu 26.04 LTS (Wayland display server).
* **Hardware:** Intel Core Ultra 7, 64GB RAM, RTX 5080 (Lokale LLM inferentie).
* **Browser Automation:** Playwright + Python via CDP (`http://localhost:9222`) gekoppeld aan een echte `google-chrome-stable` instantie met een persistent profiel (`~/.config/chrome-ah-profile`), draaiend via `xvfb-run` (`--ozone-platform=x11`) om WAF-blokkades (zoals Akamai bij AH) te vermijden.
* **LLM (Brein):** `qwen3-coder:30b` lokaal gehost via Ollama (`http://localhost:11434/api/generate`, met `num_ctx: 16384` en `temperature: 0.0`).
* **Notificaties:** Telegram Bot API (geformatteerd in Telegram-compatibele Markdown).

## 📂 Bestandsstructuur
* `start_browser.sh` & `start_browser_xvfb.sh` — Starten Chrome met remote debugging op poort 9222 (zichtbaar voor initiële sessie/cookies of onzichtbaar via Xvfb).
* `extract_supermarkten.py` — Multi-store scraper die door alle zoektermen en winkels loopt, inclusief scroll-functie voor lazy loading, en semantische DOM-context wegschrijft naar `data.json`.
* `analyseer_promos.py` — Deal-geheugen check (`seen_promos.json`), 2-traps LLM Map-Reduce analyse via Ollama, variant-groepering en verzending naar Telegram.
* `run_agent.sh` — Overkoepelend script dat `.env` inlaadt, Xvfb-Chrome beheert en de volledige pijplijn (`extract_supermarkten.py` ➔ `analyseer_promos.py`) uitvoert.
* `.env` & `.env.example` — Omgevingsvariabelen voor `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `OLLAMA_URL` en `OLLAMA_MODEL` (nooit gecommit in Git).
* `data.json` — Gegenereerde dataset met alle gevonden producten en hun semantische context (lokaal, genegeerd door Git).
* `seen_promos.json` — Lokaal geheugen op het niveau van individuele actieve deals (SHA-256 hash van supermarkt + titel + promotie + stukprijs).
* `laatste_bericht.json` — Log van het laatst succesvol verzonden Telegram-bericht.

## ✅ Wat we al hebben gebouwd (Voltooid)
1. **WAF-vrije Browser & Spookscherm:** Chrome draait met een persistent gebruikersprofiel op poort 9222 (zichtbaar of via `xvfb-run`), waardoor Albert Heijn, Colruyt en Delhaize probleemloos geladen worden.
2. **Dynamische Multi-Store & Zoekterm Loop (`extract_supermarkten.py`):**
   * *Zoektermen:* `["hipro", "barebells", "holie", "melkunie protein", "nakd protein", "upfront", "eiwitreep", "protein bar"]`
   * *Winkels & URL's:*
     * **Albert Heijn:** `https://www.ah.be/zoeken?query={query}`
     * **Colruyt (Collect&Go):** `https://www.collectandgo.be/nl/zoek?searchTerm={query}`
     * **Delhaize:** `https://www.delhaize.be/shop/search?q={query}%3Arelevance&text={query}&sort=relevance`
3. **Universele Semantische DOM-Extractie:**
   * Geen hardcoded productfiltering in Python.
   * Gebruikt Europese toegankelijkheidsattributen (`aria-label`, `.sr-only`, `data-testid`) uit de productkaarten om elk product expliciet te voorzien van gestructureerde velden in `semantische_context`:
     * Eerste veld is altijd `PROMOTIE_ACTIEF: <actie>` of `GEEN_PROMOTIE (standaardprijs)` (cruciaal om aandacht-verschrijvingen bij causale LLM's te voorkomen).
     * Gevolgd door `titel: ...`, `stukprijs: ...` en `eenheid: ...`.
4. **2-Staps LLM Map-Reduce & Variant-Groepering (`analyseer_promos.py`):**
   * **Stap 1 (Extractie per winkel):** Ollama filtert per supermarkt alle items met `PROMOTIE_ACTIEF` (inclusief hun `deal_status`) uit `data.json`.
   * **Stap 2 (Berekening, Groepering & Opmaak):** Ollama berekent de effectieve stukprijs (bijv. `1+1 gratis` = `0.50 * stukprijs`, `2de tegen -50%` = `0.75 * stukprijs`), voegt verschillende smaken/varianten van hetzelfde merk samen op één enkele regel met prijsrange, markeert nieuwe deals met `🆕` en lopende deals met `(loopt nog)`, en maakt het bericht op in zuivere Telegram Markdown (enkele `*` voor vet, geen `#` titels).
5. **Slimme Anti-Spam op Deal-niveau (`seen_promos.json`):**
   * Lokaal geheugen per individuele actieve deal (SHA-256 hash van `supermarkt | titel | promotie | stukprijs`).
   * **Geen nieuwe deals = Geen spam (en geen onnodige LLM-calls):** Zolang alle actieve promoties ongewijzigd doorlopen, wordt er geen nieuw Telegram-bericht verstuurd.
   * **Nieuwe of scherpere deal:** Zodra er minstens één nieuwe promo (of prijsverlaging) opduikt, wordt het overzicht verstuurd met `🆕` bij de nieuwe deals en `(loopt nog)` bij de doorlopende deals.
   * **Automatische opschoning:** Zodra een promo bij een winkel afloopt, verdwijnt die uit `seen_promos.json`, zodat dezelfde actie weken later weer als `🆕` gemeld wordt.

## 🚀 Deel 2 (Roadmap): Interactieve Personal Promo-Agent via Telegram
Van een eenrichtings-cronjob naar een tweerichtings **Personal Agent**:
1. **Autonome Periodieke Scanner (Proactief):**
   * Blijft op vaste tijdstippen zelfstandig de vaste lijst van sport-/eiwitproducten controleren en stuurt een melding zodra er nieuwe deals opduiken.
2. **On-Demand Zoekopdrachten via Telegram (Reactief):**
   * Je stuurt via Telegram een natuurlijk bericht naar de bot (bijv. *"Zoek eens of er ergens promo is op kipfilet of skyr bij AH en Colruyt"* of *"Check even pindakaas bij Delhaize"*).
   * De Personal Agent haalt via het lokale LLM (`qwen3-coder:30b`) de **zoektermen** en **doelwinkels** uit je bericht, start op de achtergrond de Playwright/Xvfb-scraper voor die specifieke query, analyseert de gevonden prijzen & promo's en antwoordt rechtstreeks in Telegram.
3. **Dynamisch Beheer van Vaste Watchlist:**
   * Mogelijkheid om via Telegram producten/merken toe te voegen aan of te verwijderen uit de wekelijkse watchlist.
