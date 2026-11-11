---
name: supermarket-promos
description: Search live for prices and promotions of specific products or brands across Belgian supermarkets (Albert Heijn, Colruyt, Delhaize) or scan the default protein watchlist.
version: 1.1.0
platforms: [linux]
metadata:
  hermes:
    tags: [Shopping, Supermarket, Promotions, Belgium, Dendermonde]
---

# Supermarket Promo & Price Finder (Belgium)

Use this skill whenever the user asks to check prices, offers, or promotions at Belgian supermarkets (**Albert Heijn / AH**, **Colruyt / Collect&Go**, or **Delhaize**).

## When to use
- The user asks generally for promotions without specifying a product (e.g., *"Are there any promos this week?"* or *"Check supermarket promotions"*).
- The user asks about a specific product or brand (e.g., *"Are there any promos on skyr or chicken breast at AH or Delhaize?"* or *"How much are Barebells right now at Colruyt?"*).

## Available Commands

### 1. Live Promo & Price Search (`search_on_demand.py`)
Run the command below via your `terminal` tool. It connects to the headless Chrome CDP service (`localhost:9222`) and prints the formatted results to stdout (without touching `data.json` or `seen_promos.json`):

```bash
# Default scan (when no specific product is mentioned — automatically scans the default protein watchlist BRANDS from extract_supermarkets.py):
/home/bavobbr/projects/proteine-agent/venv/bin/python /home/bavobbr/projects/proteine-agent/search_on_demand.py --stores "<ah|colruyt|delhaize|all>" --only-promos

# Specific product or brand search:
/home/bavobbr/projects/proteine-agent/venv/bin/python /home/bavobbr/projects/proteine-agent/search_on_demand.py --queries "<comma_separated_queries>" --stores "<ah|colruyt|delhaize|all>"
```

**Parameters:**
- `--queries` / `-q` *(optional)*:
  - **If the user does NOT specify a product:** Omit `--queries` (or pass `--queries default`). The script automatically scans the default protein watchlist defined in `extract_supermarkets.py`: `hipro, barebells, holie, melkunie protein, nakd protein, upfront, xxl nutrition, eiwitreep, protein bar`.
  - **If the user specifies products/brands:** Pass comma-separated Dutch or brand search terms, e.g. `"skyr,kipfilet"` or `"hipro,barebells"`.
- `--stores` / `-s` *(optional, default `all`)*: Comma-separated stores: `ah`, `colruyt`, `delhaize`, or `all`.
- `--only-promos` *(optional)*: Include this flag if the user only wants to see active promotions and no standard prices.
- `--json` *(optional)*: Returns raw JSON instead of a formatted Markdown report.

### 2. Guidelines for Replying to the User
> **Preference Precedence:** Any user preferences stored in `USER.md` or `MEMORY.md` (or stated in the current conversation) **override** the default discount rules below.

1. **Default discount filter — Focus on major deals (>= 50% effective discount per item):**
   - Prioritize `1+1 gratis` (1+1 free = `0.50 * unit_price`), `2e gratis` (2nd free = `0.50 * unit_price`), `2+2 gratis`, and `-50%` or higher discounts.
   - Ignore minor discounts (`-10%`, `-25%`, or `2de tegen -50%` which is only 25% off) unless the user specifically asks for all prices/discounts or has saved a different preference.
2. **Group flavors/variants** of the same brand on a single line where applicable.

### 3. Learning & Updating Promo Rules Over Time (MANDATORY)
- **Whenever the user states a standing preference, default behavior, or correction** (e.g., *"When I don't specify X, do Y"*, *"Include 2+1 gratis"*, *"Ignore brand Z"*), you **MUST immediately in the same turn**:
  1. Call `memory(action="add", target="memory", content="...")` to persist the rule in `MEMORY.md`.
  2. Update `/home/bavobbr/projects/proteine-agent/skills/supermarket-promos/SKILL.md` (via `patch` or `write_file`) so this skill file reflects the updated rule.
- **Weekly cron pipeline rules:** If the user also wants that change applied to the automated Monday morning cron job, update `/home/bavobbr/projects/proteine-agent/analyze_promos.py` (and `BRANDS` in `/home/bavobbr/projects/proteine-agent/extract_supermarkets.py` if adding/removing default watchlist brands).
