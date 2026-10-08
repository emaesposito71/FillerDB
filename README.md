# FillerDB

Dump mensile delle Quick List di [animefillerlist.com](https://www.animefillerlist.com/)
(canon / mixed / filler per episodio) in JSON statici, per l'app Quarto Gradino.

Perché un dump e non scraping a runtime: se il sito restyla o va giù, si rompe
solo questo script (visibile nei log dell'Action) mentre l'app serve l'ultimo
dump buono. A runtime zero dipendenze, zero rate-limit.

## Layout

- `shows/<slug>.json` — un anime: `{slug, title, updated, canon, mixed, filler}`
  con range compatti (`[[1,6],[8,8],…]` = episodi inclusi).
- `index.json` — `{slug: [varianti normalizzate del titolo…]}` per il matching.
- `scripts/dump_afl.py` — lo script (solo stdlib Python, niente dipendenze).

## Formato esempio (`shows/naruto.json`)

```json
{
  "slug": "naruto",
  "title": "Naruto",
  "updated": "2026-10-08",
  "canon": [[1,6],[8,8],[10,13]],
  "mixed": [[7,7],[9,9],[14,16]],
  "filler": [[26,26],[97,97],[101,106]]
}
```

## Matching titoli (lato app)

Normalizzare il titolo eng/romaji e confrontare con le varianti in `index.json`.
L'algoritmo **deve** restare identico qui e in Kotlin:

1. minuscolo
2. NFD + rimozione diacritici (categoria Unicode Mn)
3. `[^a-z0-9]+` → spazio singolo, trim

Se nessuno matcha: fallback sul dato Tenrai/runtime (niente mixed per la nicchia).

## Schedulazione

Action mensile (`0 3 1 * *`) + `workflow_dispatch`. Gli show conclusi non cambiano
mai; quelli in corso si aggiornano al giro dopo. Episodi oltre il max listato =
sconosciuti (l'app usa il fallback).
