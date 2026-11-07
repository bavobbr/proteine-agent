---
name: supermarkt-promos
description: Zoek live naar prijzen en promoties van specifieke producten of merken bij Belgische supermarkten (Albert Heijn, Colruyt, Delhaize) of draai de wekelijkse eiwit-promo check.
version: 1.0.0
platforms: [linux]
metadata:
  hermes:
    tags: [Shopping, Supermarkt, Promoties, België, Dendermonde]
---

# Supermarkt Promo & Prijs Zoeker (België)

Gebruik deze skill wanneer de gebruiker vraagt om prijzen, aanbiedingen of promoties op te zoeken bij Belgische supermarkten (**Albert Heijn / AH**, **Colruyt / Collect&Go**, of **Delhaize**).

## Wanneer gebruiken?
- De gebruiker vraagt bijv.: *"Staat er ergens skyr of kipfilet in promo bij AH of Delhaize?"*
- De gebruiker wil prijzen vergelijken van een specifiek merk of product (bijv. *"Wat kost Barebells of pindakaas momenteel bij Colruyt?"*).
- De gebruiker vraagt om de volledige eiwit-watchlist scan nu meteen uit te voeren.

## Beschikbare Commando's

### 1. Gericht zoeken op product of merk (On-Demand)
Voer het onderstaande commando uit via je shell/terminal tool. Dit script start zelf onzichtbaar Chrome via Xvfb (indien nog niet actief) en raakt de wekelijkse `data.json` of `seen_promos.json` **niet** aan:

```bash
/home/bavobbr/projects/proteine-agent/venv/bin/python /home/bavobbr/projects/proteine-agent/search_on_demand.py --queries "<zoektermen_komma_gescheiden>" --stores "<winkels>"
```

**Parameters:**
- `--queries` / `-q` *(verplicht)*: Komma-gescheiden zoektermen, bijv. `"skyr,kipfilet"` of `"hipro,barebells"`.
- `--stores` / `-s` *(optioneel, standaard `all`)*: Komma-gescheiden winkels: `ah`, `colruyt`, `delhaize` of `all`.
- `--only-promos` *(optioneel)*: Voeg deze vlag toe als de gebruiker uitsluitend actieve promoties wil zien en geen standaardprijzen.
- `--json` *(optioneel)*: Geeft ruwe JSON terug in plaats van een geformatteerd Markdown-overzicht.

**Voorbeeld:**
```bash
/home/bavobbr/projects/proteine-agent/venv/bin/python /home/bavobbr/projects/proteine-agent/search_on_demand.py --queries "skyr" --stores "ah,delhaize"
```

### 2. Richtlijnen voor je antwoord aan de gebruiker
1. **Reken actieprijzen om naar de effectieve prijs per stuk:**
   - `1+1 gratis` = `0.50 * stukprijs` (50% korting bij aankoop van 2)
   - `2de tegen -50%` = `0.75 * stukprijs` (25% korting bij aankoop van 2)
   - `-25% vanaf 2 st` = `0.75 * stukprijs`
   - `-10% vanaf 4 st` = `0.90 * stukprijs`
2. **Groepeer smaken/varianten** van hetzelfde merk overzichtelijk op één regel waar mogelijk.

### 3. Volledige wekelijkse eiwit-promo pijplijn uitvoeren
Als de gebruiker expliciet vraagt om de volledige vaste eiwit-watchlist te draaien en naar Telegram te sturen:
```bash
/home/bavobbr/projects/proteine-agent/run_agent.sh
```
