# Project Context: Local AI Promo-Agent (Dendermonde)

## 🎯 Use Case
Bavo (45) and his son Mauro (17) play a lot of sports (field hockey, gym, core stability) and consume high-protein bars and drinks. These products (such as HiPRO, Barebells, Holie's, Upfront) are relatively expensive at full price (€1.50 – €3.00 per item). In Dendermonde (Belgium), local supermarkets (Albert Heijn, Colruyt, Delhaize) frequently run `1+1 free`, `2nd at -50%`, or volume discounts.

**Goal:** Run a 100% local, autonomous AI agent on Ubuntu 26.04 that invisibly scrapes these supermarkets every week, analyzes prices and promotions using a local LLM (without fragile hardcoded Python product filters), and notifies Bavo via Telegram with a clean, grouped promo summary.

## 🛠️ Architecture & Tech Stack
* **OS:** Ubuntu 26.04 LTS (Wayland display server).
* **Hardware:** Intel Core Ultra 7, 64GB RAM, RTX 5080 (Local LLM inference).
* **Browser Automation:** Playwright + Python over CDP (`http://localhost:9222`) connected to a real `google-chrome-stable` instance with a persistent profile (`~/.config/chrome-ah-profile`), running under `xvfb-run` (`--ozone-platform=x11`) to bypass WAF blocks (such as Akamai on AH).
* **LLM (Brain):** `qwen3-coder:30b` hosted locally via Ollama (`http://localhost:11434/api/generate`, with `num_ctx: 16384` and `temperature: 0.0`).
* **Notifications:** Telegram Bot API (formatted in Telegram-compatible Markdown).

## 📂 File Structure
* `start_browser.sh` & `start_browser_xvfb.sh` — Launch Chrome with remote debugging on port 9222 (visible for initial session/cookies or invisible via Xvfb).
* `extract_supermarkets.py` — Multi-store scraper that iterates across all search queries and supermarkets, including smooth scrolling for lazy-loaded cards, writing semantic DOM context to `data.json`.
* `analyze_promos.py` — Deal-memory check (`seen_promos.json`), 2-stage LLM Map-Reduce analysis via Ollama, variant grouping, and Telegram delivery.
* `search_on_demand.py` — On-demand CLI wrapper (reusing `extract_supermarkets.py` and `analyze_promos.py`) for live ad-hoc product/promo queries from a Personal Agent without touching `data.json`.
* `skills/supermarket-promos/SKILL.md` — Open `SKILL.md` definition for integrating this project as a tool/skill inside **Hermes Agent**, **OpenClaw**, or **Antigravity**.
* `run_agent.sh` — Master wrapper script that loads `.env`, manages Xvfb-Chrome, and executes the full pipeline (`extract_supermarkets.py` ➔ `analyze_promos.py`).
* `.env` & `.env.example` — Environment variables for `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `OLLAMA_URL`, and `OLLAMA_MODEL` (never committed to Git).
* `data.json` — Generated dataset containing all scraped products and their semantic context (local, ignored by Git).
* `seen_promos.json` — Local deal-level memory of active promotions (SHA-256 hash of `supermarket | title | promotion | unit_price`).
* `last_message.json` — Log of the last successfully delivered Telegram message.

## ✅ Completed Milestones (Phase 1)
1. **WAF-Free Browser & Virtual Display:** Chrome runs with a persistent user profile on port 9222 (visible or via `xvfb-run`), loading Albert Heijn, Colruyt, and Delhaize reliably.
2. **Dynamic Multi-Store & Search Query Loop (`extract_supermarkets.py`):**
   * *Queries:* `["hipro", "barebells", "holie", "melkunie protein", "nakd protein", "upfront", "xxl nutrition", "eiwitreep", "protein bar"]`
   * *Stores & URLs:*
     * **Albert Heijn:** `https://www.ah.be/zoeken?query={query}`
     * **Colruyt (Collect&Go):** `https://www.collectandgo.be/nl/zoek?searchTerm={query}`
     * **Delhaize:** `https://www.delhaize.be/shop/search?q={query}%3Arelevance&text={query}&sort=relevance`
3. **Universal Semantic DOM Extraction:**
   * No hardcoded product filtering in Python.
   * Uses European accessibility attributes (`aria-label`, `.sr-only`, `data-testid`) from product cards to populate structured fields in `semantic_context`:
     * First field is always `PROMO_ACTIVE: <deal>` or `NO_PROMO (standard price)` (critical to prevent attention drift in causal LLMs).
     * Followed by `title: ...`, `unit_price: ...`, and `unit: ...`.
4. **2-Stage LLM Map-Reduce & Variant Grouping (`analyze_promos.py`):**
   * **Step 1 (Per-store extraction):** Ollama filters all items with `PROMO_ACTIVE` (including their `deal_status`) per supermarket from `data.json`.
   * **Step 2 (Calculation, Grouping & Formatting):** Ollama calculates the effective unit price (e.g., `1+1 gratis` = `0.50 * unit_price`, `2de tegen -50%` = `0.75 * unit_price`), merges multiple flavors/variants of the same brand onto a single line with a price range, marks new deals with `🆕` and ongoing deals with `(still running)`, and formats the message in clean Telegram Markdown (single `*` for bold, no `#` headers).
5. **Smart Deal-Level Anti-Spam (`seen_promos.json`):**
   * Local memory per individual active deal (SHA-256 hash of `supermarket | title | promotion | unit_price`).
   * **No new deals = No spam (and no wasted LLM calls):** As long as all active promotions continue unchanged, no duplicate Telegram alert is sent.
   * **New or deeper discount:** As soon as at least one new promo (or price drop) appears, the overview is sent with `🆕` on new deals and `(still running)` on ongoing deals.
   * **Automatic cleanup:** Once a promotion ends at a store, it is automatically pruned from `seen_promos.json` so that if the same promo returns weeks later, it triggers as `🆕` again.

## 🚀 Phase 2: Personal Agent Skill Integration (Hermes Agent / OpenClaw)
1. **Non-Destructive On-Demand Search (`search_on_demand.py`):**
   * Reuses `SUPERMARKETS` and `extract_page` from `extract_supermarkets.py` to search any product or brand across any subset of stores on demand, returning clean Markdown or JSON to `stdout` without overwriting `data.json` or `seen_promos.json`.
2. **Standardized Agent Skill (`skills/supermarket-promos/SKILL.md`):**
   * Exposes both the on-demand search and the full weekly pipeline as an Agent Skill that can be symlinked into `~/.hermes/skills/supermarket-promos` in a separate `personal-agent` project.
