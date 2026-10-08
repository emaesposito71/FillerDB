#!/usr/bin/env python3
"""Dump delle Quick List di animefillerlist.com + mapping verso AnimeUnity.

Fase 1 (dump): /shows -> per slug parse del blocco #Condensed (canon/mixed/
  filler), fallback sulla tabella EpisodeList, guardia sul titolo (il sito ha
  slug avvelenati che mostrano un ALTRO show: senza match si scarta e si
  cancella il file esistente). Scrive shows/<slug>.json + index.json.
Fase 2 (map): per ogni show, cerca il titolo su AnimeUnity (/archivio?title=)
  e registra map.json {anilist_id: slug} su match ESATTO normalizzato.
  overrides.json integra a mano ({force_keep: [...], map: {...}}).

Uso:
    python scripts/dump_afl.py [--out ROOT] [--max N] [--slug S ...]
                               [--sleep S] [--au-base URL]
                               [--skip-map] [--map-only]
"""

import argparse
import json
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

BASE = "https://www.animefillerlist.com"
UA = {"User-Agent": "Mozilla/5.0 (compatible; FillerDB-bot/1.0)"}

KINDS = (("manga_canon", "canon"), ("mixed_canon/filler", "mixed"), ("filler", "filler"))


def fetch(url: str, timeout: int = 30) -> str:
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


def nospace(s: str) -> str:
    return normalize(s).replace(" ", "")


def show_slugs(home_html: str) -> list:
    return sorted(set(re.findall(r'href="/shows/([a-z0-9-]+)"', home_html)))


def expand_ranges(texts: list) -> set:
    eps = set()
    for a in texts:
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
    return eps


def parse_condensed(html: str) -> dict:
    out = {}
    for cls, kind in KINDS:
        m = re.search(
            r'<div class="%s">.*?<span class="Episodes">(.*?)</span>' % re.escape(cls),
            html,
            re.S,
        )
        eps = set()
        if m:
            texts = re.findall(r"<a[^>]*>([^<>]+)</a>", m.group(1))
            eps = expand_ranges(texts)
        out[kind] = sorted(eps)
    return out


def parse_table(html: str) -> dict:
    """Fallback: tabella EpisodeList (stesse classi per riga)."""
    out = {"canon": set(), "mixed": set(), "filler": set()}
    for m in re.finditer(
        r'<tr class="(manga_canon|mixed_canon/filler|filler)\b[^"]*"[^>]*>'
        r'.*?<td class="Number">(\d+)</td>',
        html,
        re.S,
    ):
        cls, num = m.group(1), int(m.group(2))
        kind = {"manga_canon": "canon", "mixed_canon/filler": "mixed", "filler": "filler"}[cls]
        out[kind].add(num)
    return {k: sorted(v) for k, v in out.items()}


def show_title(html: str) -> str:
    m = re.search(r"<h1>(.*?) Filler List</h1>", html, re.S)
    if not m:
        return ""
    t = m.group(1).replace("&quot;", '"').replace("&#039;", "'").replace("&amp;", "&")
    return re.sub(r"\s+", " ", t).strip()


def title_matches(slug: str, title: str) -> bool:
    """Il titolo pagina deve corrispondere allo slug, altrimenti e' una pagina
    avvelenata (slug riciclati che mostrano un altro show)."""
    st = set(normalize(slug.replace("-", " ")).split())
    tt = set(normalize(title).split())
    if not st or not tt:
        return False
    if st <= tt or tt <= st:
        return True
    return nospace(slug.replace("-", " ")) == nospace(title)


def compact(nums: list) -> list:
    runs = []
    for n in nums:
        if runs and n == runs[-1][1] + 1:
            runs[-1][1] = n
        else:
            runs.append([n, n])
    return runs


def dump_show(root: Path, slug: str, force_keep: set, sleep_s: float):
    """Ritorna (title, ok). Scrive/cancella shows/<slug>.json."""
    target = root / "shows" / f"{slug}.json"
    try:
        html = fetch(f"{BASE}/shows/{slug}")
    except Exception as e:
        print(f"[!] {slug}: download fallito ({e})")
        return None, False
    title = show_title(html)
    if not title or (not title_matches(slug, title) and slug not in force_keep):
        if target.exists():
            target.unlink()
            print(f"[!] {slug:55s} titolo '{title}' non matcha: FILE AVVELENATO RIMOSSO")
        else:
            print(f"[!] {slug:55s} titolo '{title}' non matcha: scartato")
        return title, False
    forced = slug in force_keep
    parsed = parse_condensed(html)
    if sum(len(v) for v in parsed.values()) == 0:
        parsed = parse_table(html)
        if sum(len(v) for v in parsed.values()) == 0:
            print(f"[!] {slug:55s} nessun episodio (ne' Condensed ne' tabella)")
            return title, False
    doc = {
        "slug": slug,
        "title": title,
        "updated": date.today().isoformat(),
        "canon": compact(parsed["canon"]),
        "mixed": compact(parsed["mixed"]),
        "filler": compact(parsed["filler"]),
    }
    (root / "shows").mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)
    flag = " (forced)" if forced else ""
    print(
        f"[+] {slug:55s} {title!r} canon={len(parsed['canon'])} "
        f"mixed={len(parsed['mixed'])} filler={len(parsed['filler'])}{flag}"
    )
    time.sleep(sleep_s)
    return title, True


# ------------------------------------------------------------ fase 2: mapping
def au_search(au_base: str, title: str) -> list:
    url = f"{au_base}/archivio?title=" + urllib.parse.quote(title)
    html = fetch(url)
    # stesso criterio di VodHtml.attr: il valore e' &quot;-escaped, finisce
    # alla prima virgoletta raw
    key = '<archivio records="'
    start = html.find(key)
    if start < 0:
        return []
    start += len(key)
    end = html.find('"', start)
    if end < 0:
        return []
    raw = html[start:end].replace("&quot;", '"').replace("&#039;", "'").replace("&amp;", "&")
    try:
        arr = json.loads(raw)
    except ValueError:
        return []
    return arr if isinstance(arr, list) else []


def map_shows(root: Path, au_base: str, overrides: dict, sleep_s: float) -> dict:
    """map.json {anilist_id: slug} via match esatto su AnimeUnity."""
    map_path = root / "map.json"
    amap = {}
    if map_path.exists():
        try:
            amap = {str(k): v for k, v in json.loads(map_path.read_text(encoding="utf-8")).items()}
        except ValueError:
            pass
    for k, v in (overrides.get("map") or {}).items():
        amap[str(k)] = v
    mapped_slugs = set(amap.values())

    show_files = sorted((root / "shows").glob("*.json")) if (root / "shows").is_dir() else []
    todo = []
    for f in show_files:
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if doc.get("slug") in mapped_slugs:
            continue
        todo.append((doc.get("slug", f.stem), doc.get("title", "")))
    print(f"[*] mapping: {len(todo)} slug da risolvere su AnimeUnity")
    unmapped = []
    for i, (slug, title) in enumerate(todo, 1):
        found = None
        try:
            for rec in au_search(au_base, title):
                if not isinstance(rec, dict):
                    continue
                aid = rec.get("anilist_id")
                if not aid:
                    continue
                cands = {
                    normalize(str(rec.get(k) or ""))
                    for k in ("title_it", "title_eng", "title")
                } | {normalize(str(rec.get("slug") or "").replace("-", " "))}
                cands.discard("")
                if normalize(title) in cands:
                    found = str(aid)
                    break
        except Exception as e:
            print(f"[!] map {slug}: errore AU ({e})")
        if found:
            amap[found] = slug
            print(f"[m {i}/{len(todo)}] {slug} -> anilist {found}")
        else:
            unmapped.append(f"{slug} | {title}")
        time.sleep(sleep_s)
    with open(map_path, "w", encoding="utf-8") as f:
        json.dump({k: amap[k] for k in sorted(amap, key=int)}, f, ensure_ascii=False, indent=1)
    if unmapped:
        print(f"[!] {len(unmapped)} slug senza match (da curare in overrides.map):")
        for u in unmapped:
            print(f"    - {u}")
    else:
        print("[=] mapping completo, nessun orfano")
    return amap


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=".", help="root del repo/output")
    ap.add_argument("--max", type=int, default=0, help="max show (0 = tutti, per test)")
    ap.add_argument("--slug", action="append", default=[], help="solo questi slug (test)")
    ap.add_argument("--sleep", type=float, default=2.0, help="pausa tra pagine (s)")
    ap.add_argument("--au-base", default="https://www.animeunity.so", help="base AnimeUnity per il mapping")
    ap.add_argument("--skip-map", action="store_true", help="solo dump, niente mapping")
    ap.add_argument("--map-only", action="store_true", help="solo mapping (usa shows/ esistenti)")
    args = ap.parse_args()

    root = Path(args.out)
    overrides = {}
    op = root / "overrides.json"
    if op.exists():
        try:
            overrides = json.loads(op.read_text(encoding="utf-8"))
        except ValueError as e:
            print(f"[!] overrides.json invalido: {e}")
    force_keep = set(overrides.get("force_keep") or [])

    if not args.map_only:
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
                title, good = dump_show(root, slug, force_keep, args.sleep)
            except Exception as e:
                print(f"[!] {slug}: errore ({e})")
                time.sleep(args.sleep)
                continue
            if good and title:
                variants = sorted({v for v in (normalize(title), slug.replace("-", " ")) if v})
                index[slug] = variants
                ok += 1
        with open(root / "index.json", "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=1)
        print(f"[=] dump ok {ok}/{len(slugs)}, index.json scritto")

    if not args.skip_map:
        map_shows(root, args.au_base.rstrip("/"), overrides, args.sleep)
    return 0


if __name__ == "__main__":
    sys.exit(main())
