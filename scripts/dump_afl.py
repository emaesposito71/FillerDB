#!/usr/bin/env python3
"""Dump delle Quick List di animefillerlist.com in shows/*.json + index.json.

Uso:
    python scripts/dump_afl.py [--out ROOT] [--max N] [--slug S ...] [--sleep S]

- Scarica /shows, estrae gli slug /shows/<slug>, per ognuno parsa il blocco
  #Condensed (manga_canon / mixed_canon/filler / filler) e scrive
  shows/<slug>.json con range compatti + index.json per il matching titoli.
- Pensato per girare mensilmente via GitHub Action (vedi .github/workflows).
- Cortesia: 2s tra una pagina e l'altra, niente parallelo.
"""

import argparse
import json
import re
import sys
import time
import unicodedata
from datetime import date
from pathlib import Path

BASE = "https://www.animefillerlist.com"
UA = {"User-Agent": "Mozilla/5.0 (compatible; FillerDB-bot/1.0)"}

KINDS = (("manga_canon", "canon"), ("mixed_canon/filler", "mixed"), ("filler", "filler"))


def fetch(url: str, timeout: int = 30) -> str:
    import urllib.request

    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        if r.status != 200:
            raise RuntimeError(f"HTTP {r.status}")
        return r.read().decode("utf-8", errors="replace")


def normalize(s: str) -> str:
    """Normalizzazione titoli (DEVE restare identica al lato app/Kotlin)."""
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def show_slugs(home_html: str) -> list:
    return sorted(set(re.findall(r'href="/shows/([a-z0-9-]+)"', home_html)))


def parse_condensed(html: str) -> dict:
    """Ritorna {canon:[ep...], mixed:[...], filler:[...]} (liste ordinate)."""
    out = {}
    for cls, kind in KINDS:
        m = re.search(
            r'<div class="%s">.*?<span class="Episodes">(.*?)</span>' % re.escape(cls),
            html,
            re.S,
        )
        eps = set()
        if m:
            for a in re.findall(r"<a[^>]*>([^<>]+)</a>", m.group(1)):
                for part in a.split(","):
                    part = part.strip()
                    if not part:
                        continue
                    if "-" in part:
                        lo_s, _, hi_s = part.partition("-")
                        try:
                            lo, hi = int(lo_s), int(hi_s)
                        except ValueError:
                            continue
                        if lo <= 0 or hi < lo:
                            continue
                        eps.update(range(lo, hi + 1))
                    else:
                        try:
                            n = int(part)
                        except ValueError:
                            continue
                        if n > 0:
                            eps.add(n)
        out[kind] = sorted(eps)
    return out


def compact(nums: list) -> list:
    """[1,2,3,5] -> [[1,3],[5,5]]."""
    runs = []
    for n in nums:
        if runs and n == runs[-1][1] + 1:
            runs[-1][1] = n
        else:
            runs.append([n, n])
    return runs


def show_title(html: str) -> str:
    m = re.search(r"<h1>(.*?) Filler List</h1>", html, re.S)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


def dump_show(root: Path, slug: str, sleep_s: float) -> bool:
    try:
        html = fetch(f"{BASE}/shows/{slug}")
    except Exception as e:
        print(f"[!] {slug}: download fallito ({e})")
        return False
    parsed = parse_condensed(html)
    total = sum(len(v) for v in parsed.values())
    if total == 0:
        print(f"[!] {slug}: nessun episodio parsato (restyle?)")
        return False
    title = show_title(html)
    doc = {
        "slug": slug,
        "title": title,
        "updated": date.today().isoformat(),
        "canon": compact(parsed["canon"]),
        "mixed": compact(parsed["mixed"]),
        "filler": compact(parsed["filler"]),
    }
    (root / "shows").mkdir(parents=True, exist_ok=True)
    with open(root / "shows" / f"{slug}.json", "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)
    variants = sorted({v for v in (normalize(title), slug.replace("-", " ")) if v})
    print(f"[+] {slug}: {title!r} canon={len(parsed['canon'])} mixed={len(parsed['mixed'])} filler={len(parsed['filler'])}")
    time.sleep(sleep_s)
    return variants


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=".", help="root del repo/output")
    ap.add_argument("--max", type=int, default=0, help="max show (0 = tutti, per test)")
    ap.add_argument("--slug", action="append", default=[], help="solo questi slug (test)")
    ap.add_argument("--sleep", type=float, default=2.0, help="pausa tra pagine (s)")
    args = ap.parse_args()

    root = Path(args.out)
    if args.slug:
        slugs = args.slug
    else:
        try:
            slugs = show_slugs(fetch(f"{BASE}/shows"))
        except Exception as e:
            print(f"[!] indice /shows non scaricato: {e}")
            return 1
    if args.max > 0:
        slugs = slugs[: args.max]
    print(f"[*] {len(slugs)} show da processare")

    index = {}
    ok = 0
    for i, slug in enumerate(slugs, 1):
        print(f"[{i}/{len(slugs)}] {slug} ...")
        try:
            variants = dump_show(root, slug, args.sleep)
        except Exception as e:
            print(f"[!] {slug}: errore ({e})")
            variants = False
            time.sleep(args.sleep)
        if variants:
            index[slug] = variants
            ok += 1
    with open(root / "index.json", "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=1)
    print(f"[=] ok {ok}/{len(slugs)}, index.json scritto")
    return 0


if __name__ == "__main__":
    sys.exit(main())
