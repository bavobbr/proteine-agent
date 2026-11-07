---
name: supermarket-promos
description: Search live for prices and promotions of specific products or brands across Belgian supermarkets (Albert Heijn, Colruyt, Delhaize) or trigger the weekly protein promo check.
version: 1.0.0
platforms: [linux]
metadata:
  hermes:
    tags: [Shopping, Supermarket, Promotions, Belgium, Dendermonde]
---

# Supermarket Promo & Price Finder (Belgium)

Use this skill whenever the user asks to check prices, offers, or promotions at Belgian supermarkets (**Albert Heijn / AH**, **Colruyt / Collect&Go**, or **Delhaize**).

## When to use
- The user asks e.g.: *"Are there any promos on skyr or chicken breast at AH or Delhaize?"*
- The user wants to compare prices of a specific brand or product (e.g. *"How much are Barebells or peanut butter right now at Colruyt?"*).
- The user asks to run the full protein watchlist scan right now.

## Available Commands

### 1. Targeted product or brand search (On-Demand)
Run the command below via your shell/terminal tool. This script automatically launches Chrome invisibly via Xvfb (if not already active) and does **not** touch the weekly `data.json` or `seen_promos.json`:

```bash
/home/bavobbr/projects/proteine-agent/venv/bin/python /home/bavobbr/projects/proteine-agent/search_on_demand.py --queries "<comma_separated_queries>" --stores "<stores>"
```

**Parameters:**
- `--queries` / `-q` *(required)*: Comma-separated search terms, e.g. `"skyr,kipfilet"` or `"hipro,barebells"`. *(Note: since Belgian supermarket websites are in Dutch, use Dutch or brand product terms like `kipfilet`, `pindakaas`, `skyr`, `eiwitreep`, `barebells` for best search hits).*
- `--stores` / `-s` *(optional, default `all`)*: Comma-separated stores: `ah`, `colruyt`, `delhaize`, or `all`.
- `--only-promos` *(optional)*: Include this flag if the user only wants to see active promotions and no standard prices.
- `--json` *(optional)*: Returns raw JSON instead of a formatted Markdown report.

**Example:**
```bash
/home/bavobbr/projects/proteine-agent/venv/bin/python /home/bavobbr/projects/proteine-agent/search_on_demand.py --queries "skyr" --stores "ah,delhaize"
```

### 2. Guidelines for replying to the user
1. **Calculate effective unit prices for promotions:**
   - `1+1 gratis` (1+1 free) = `0.50 * unit_price` (50% discount when buying 2)
   - `2de tegen -50%` (2nd at -50%) = `0.75 * unit_price` (25% discount when buying 2)
   - `-25% vanaf 2 st` (-25% from 2 pcs) = `0.75 * unit_price`
   - `-10% vanaf 4 st` (-10% from 4 pcs) = `0.90 * unit_price`
2. **Group flavors/variants** of the same brand on a single line where applicable.

### 3. Run the full weekly protein promo pipeline
If the user explicitly asks to run the full protein watchlist scan and send the summary to Telegram:
```bash
/home/bavobbr/projects/proteine-agent/run_agent.sh
```
