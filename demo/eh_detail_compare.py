# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "curl-cffi",
#   "beautifulsoup4",
#   "lxml",
#   "psycopg[binary]",
#   "python-dotenv",
# ]
# ///
"""
Compare a single exhentai gallery detail page against the DB row.

Goal: detail pages are expensive (rate-limited, ban-prone), but the current
parser only extracts a subset of what's on the page. This demo fetches ONE
detail page, parses EVERYTHING that's structurally present, then diffs
against the eh_galleries row to surface what information is being thrown away.

Usage:
    uv run demo/eh_detail_compare.py                    # pick a random synced row
    uv run demo/eh_detail_compare.py --gid 4012603      # specific gid
    uv run demo/eh_detail_compare.py --save-html /tmp/detail.html

Env (read from .env or shell):
    EX_COOKIES   — exhentai cookie string (same format as scraper-go)
    EX_BASE_URL  — default https://exhentai.org
    PROXY_URL    — optional HTTP proxy (e.g. http://192.168.0.110:7890)
    DATABASE_URL — postgres DSN, default points at pi's exposed port
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field, asdict
from typing import Any

from bs4 import BeautifulSoup, Tag
from curl_cffi.requests import Session
from dotenv import load_dotenv
import psycopg

GID_TOKEN_RE = re.compile(r"/g/(\d+)/([a-f0-9]+)/")
SPACE_RE = re.compile(r"\s+")
THUMB_URL_RE = re.compile(r"url\((.+?)\)")
RATING_RE = re.compile(r"([0-5](?:\.\d+)?)")
RATING_COUNT_RE = re.compile(r"(\d[\d,]*)\s*ratings?", re.IGNORECASE)
BG_POS_RE = re.compile(r"background-position\s*:\s*(-?\d+)px\s+(-?\d+)px")


def normalize_text(value: str | None) -> str:
    return SPACE_RE.sub(" ", value or "").strip()


def parse_cookie_string(raw: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    if not raw:
        return cookies
    for pair in raw.split(";"):
        if "=" not in pair:
            continue
        k, v = pair.split("=", 1)
        k, v = k.strip(), v.strip()
        if k and v:
            cookies[k] = v
    return cookies


# ──────────────────────────────────────────────────────────────────────────────
# Comprehensive detail parser — extracts EVERYTHING structurally visible,
# including fields the production parser (parser.go ParseDetail) drops.
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class TorrentInfo:
    name: str
    size: str | None = None
    seeds: int | None = None
    peers: int | None = None
    downloads: int | None = None
    poster: str | None = None
    posted: str | None = None
    hash: str | None = None
    url: str | None = None


@dataclass
class CommentInfo:
    author: str
    author_url: str | None
    posted: str
    score: int | None
    text: str
    is_uploader_comment: bool = False


@dataclass
class TagEntry:
    namespace: str
    value: str
    power: str  # "weak" | "strong" | ""  (from CSS class on the <a>)
    href: str | None = None


@dataclass
class PagePreview:
    index: int
    thumb_url: str | None
    page_url: str | None
    caption: str | None = None


@dataclass
class FullDetail:
    # ── fields the production parser already extracts ──
    title: str = ""
    title_jpn: str = ""
    category: str = ""
    uploader: str = ""
    uploader_url: str | None = None
    rating: float | None = None
    rating_count: int | None = None       # NEW — number of raters
    thumb: str = ""
    posted: str = ""
    parent_url: str | None = None         # NEW — parent gallery link
    visible: str | None = None            # NEW — visibility flag
    language: str = ""
    file_size: str | None = None          # NEW — raw file size string
    pages: int = 0
    fav_count: int = 0
    comment_count: int = 0
    tags: dict[str, list[str]] = field(default_factory=dict)
    # ── fields the production parser drops entirely ──
    tag_entries: list[TagEntry] = field(default_factory=list)   # NEW — with power
    torrents: list[TorrentInfo] = field(default_factory=list)   # NEW
    comments: list[CommentInfo] = field(default_factory=list)   # NEW — actual content
    page_previews: list[PagePreview] = field(default_factory=list)  # NEW — gdt grid
    archiver_url: str | None = None       # NEW — archive download link
    showpage_url: str | None = None       # NEW — first page link
    is_deleted: bool = False              # NEW — expunged banner detection
    torrent_count: int = 0                # NEW — "(N)" in Torrent Download link
    expunge_petition_url: str | None = None  # NEW — "Petition to Expunge" link
    rename_petition_url: str | None = None   # NEW — "Petition to Rename" link


def parse_full_detail(html: str) -> FullDetail:
    soup = BeautifulSoup(html, "lxml")
    d = FullDetail()

    # Expunged / deleted detection
    if soup.find(string=re.compile(r"This gallery has been removed", re.IGNORECASE)):
        d.is_deleted = True
    if soup.find(class_=re.compile(r"gp", re.I)) and soup.find(class_=re.compile(r"removed|deleted|expunged", re.I)):
        d.is_deleted = True

    gm = soup.find(class_="gm")
    if not gm:
        return d

    # Title / title_jpn
    gn = gm.find(id="gn")
    gj = gm.find(id="gj")
    d.title = normalize_text(gn.get_text(" ", strip=True)) if gn else ""
    d.title_jpn = normalize_text(gj.get_text(" ", strip=True)) if gj else ""

    # Category
    ce = gm.find(class_="cn") or gm.find(class_="cs")
    d.category = normalize_text(ce.get_text(" ", strip=True)) if ce else ""

    # Uploader (+ profile link)
    gdn = gm.find(id="gdn")
    if gdn:
        d.uploader = normalize_text(gdn.get_text(" ", strip=True))
        a = gdn.find("a")
        if a and a.get("href"):
            d.uploader_url = a["href"]

    # Rating + rating count
    rating_label = gm.find(id="rating_label")
    if rating_label:
        rtext = normalize_text(rating_label.get_text(" ", strip=True))
        if "Not Yet Rated" not in rtext:
            m = RATING_RE.search(rtext)
            if m:
                d.rating = float(m.group(1))
        # rating count often lives in #rating_count span
        rc = soup.find(id="rating_count")
        if rc:
            rc_text = normalize_text(rc.get_text(" ", strip=True))
            m = RATING_COUNT_RE.search(rc_text) or re.search(r"(\d[\d,]*)", rc_text)
            if m:
                d.rating_count = int(m.group(1).replace(",", ""))
        else:
            # Fallback: scan rating_label siblings
            m = RATING_COUNT_RE.search(rtext)
            if m:
                d.rating_count = int(m.group(1).replace(",", ""))

    # Cover thumb
    gd1 = gm.find(id="gd1")
    if gd1:
        div = gd1.find("div")
        if div:
            style = div.get("style", "")
            m = THUMB_URL_RE.search(style)
            if m:
                d.thumb = m.group(1).strip("'\"")

    # Detail table #gdd — capture ALL rows, not just the 4 the prod parser knows
    gdd = gm.find(id="gdd")
    if gdd:
        for tr in gdd.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 2:
                continue
            key = normalize_text(tds[0].get_text(" ", strip=True))
            value = normalize_text(tds[1].get_text(" ", strip=True))
            # Capture links inside value (e.g. Parent: <a>)
            link = tds[1].find("a")
            link_href = link["href"] if link and link.get("href") else None

            if key.startswith("Posted"):
                d.posted = value
            elif key.startswith("Parent"):
                d.parent_url = link_href
            elif key.startswith("Visible"):
                d.visible = value
            elif key.startswith("Language"):
                d.language = value
            elif key.startswith("File Size"):
                d.file_size = value
            elif key.startswith("Length"):
                idx = value.find(" ")
                if idx >= 0:
                    try:
                        d.pages = int(value[:idx].replace(",", ""))
                    except ValueError:
                        pass
            elif key.startswith("Favorited"):
                if value == "Never":
                    d.fav_count = 0
                elif value == "Once":
                    d.fav_count = 1
                else:
                    idx = value.find(" ")
                    if idx >= 0:
                        try:
                            d.fav_count = int(value[:idx].replace(",", ""))
                        except ValueError:
                            d.fav_count = 0

    # Comment count + actual comments
    cdiv = soup.find(id="cdiv")
    if cdiv:
        c1s = cdiv.find_all(class_="c1")
        d.comment_count = len(c1s)
        for c1 in c1s[:5]:  # keep first 5 for the demo
            author = ""
            author_url = None
            posted = ""
            score: int | None = None
            text = ""
            is_uploader = False

            c3 = c1.find(class_="c3")
            if c3:
                c3_text = normalize_text(c3.get_text(" ", strip=True))
                # "Posted on 26 June 2026, 15:56 by: 114514beastman"
                m = re.search(r"Posted on\s+(.+?)\s+by:", c3_text)
                if m:
                    posted = m.group(1).strip()
                a = c3.find("a", href=True)
                if a:
                    author = normalize_text(a.get_text(" ", strip=True))
                    author_url = a["href"]

            c4 = c1.find(class_="c4")
            if c4:
                c4_text = normalize_text(c4.get_text(" ", strip=True))
                if "Uploader Comment" in c4_text:
                    is_uploader = True

            # Comment text lives in .c6 (NOT .c5). .c7 holds the vote tally
            # (often empty/hidden until expanded).
            c6 = c1.find(class_="c6")
            if c6:
                text = normalize_text(c6.get_text(" ", strip=True))

            c7 = c1.find(class_="c7")
            if c7:
                c7_text = normalize_text(c7.get_text(" ", strip=True))
                m = re.search(r"(-?\d+)", c7_text)
                if m:
                    score = int(m.group(1))

            d.comments.append(CommentInfo(
                author=author, author_url=author_url, posted=posted,
                score=score, text=text[:200], is_uploader_comment=is_uploader,
            ))

    # Tags — capture namespace + value + power (weak/strong via CSS class)
    taglist = soup.find(id="taglist")
    if taglist:
        for tr in taglist.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 2:
                continue
            ns = normalize_text(tds[0].get_text(" ", strip=True)).rstrip(":") or "misc"
            values: list[str] = []
            for div in tds[1].find_all("div"):
                # Power lives on the wrapping <div>: class="gtl" = weak,
                # class="gt" = strong. The <a> inside has empty class.
                div_classes = div.get("class") or []
                power = ""
                if "gtl" in div_classes:
                    power = "weak"
                elif "gt" in div_classes or "gtw" in div_classes:
                    power = "strong"
                a = div.find("a")
                if not a:
                    continue
                val = normalize_text(a.get_text(" ", strip=True))
                if not val:
                    continue
                values.append(val)
                d.tag_entries.append(TagEntry(
                    namespace=ns,
                    value=val,
                    power=power,
                    href=a.get("href"),
                ))
            if values:
                d.tags[ns] = values

    # Torrents (#gd5) — the torrent list itself is behind a popup, but the
    # count is inline as "Torrent Download (N)". Also capture the
    # archive-download popup URL and the expunge/rename petition links.
    gd5 = soup.find(id="gd5")
    if gd5:
        gd5_html = str(gd5)
        # Archive download: popUp('https://.../archiver.php?gid=...&token=...',480,320)
        m = re.search(r"popUp\(\s*'(https?://[^']+archiver[^']+)'", gd5_html)
        if m:
            d.archiver_url = m.group(1).replace("&amp;", "&")
        # Torrent count: "Torrent Download (24)"
        m = re.search(r"Torrent Download\s*\((\d+)\)", gd5_html)
        if m:
            d.torrent_count = int(m.group(1))
        # Petition links
        for a in gd5.find_all("a", href=True):
            href = a["href"]
            text = normalize_text(a.get_text(" ", strip=True))
            if "Petition to Expunge" in text:
                d.expunge_petition_url = href
            elif "Petition to Rename" in text:
                d.rename_petition_url = href

    # Fallback: scan whole document for archiver popUp if gd5 missed it
    if not d.archiver_url:
        m = re.search(r"popUp\(\s*'(https?://[^']+archiver[^']+)'", html)
        if m:
            d.archiver_url = m.group(1).replace("&amp;", "&")

    # Page preview grid (#gdt)
    gdt = soup.find(id="gdt")
    if gdt:
        for i, a in enumerate(gdt.find_all("a", href=True), start=1):
            thumb_url = None
            img = a.find("img")
            if img:
                thumb_url = img.get("src") or img.get("data-src")
            d.page_previews.append(PagePreview(
                index=i,
                thumb_url=thumb_url,
                page_url=a["href"],
                caption=normalize_text(a.get_text(" ", strip=True)) or None,
            ))
        if not d.page_previews:
            # Compact mode: <div class="gdtm"> with style-based thumb
            for i, gdtm in enumerate(gdt.find_all(class_=re.compile(r"gdtm")), start=1):
                style = gdtm.get("style", "")
                m = THUMB_URL_RE.search(style)
                thumb_url = m.group(1).strip("'\"") if m else None
                a = gdtm.find("a", href=True)
                d.page_previews.append(PagePreview(
                    index=i,
                    thumb_url=thumb_url,
                    page_url=a["href"] if a else None,
                ))

    # First-page link (gpc / showpage)
    gpc = soup.find(id="gpc")
    if gpc:
        a = gpc.find("a", href=True)
        if a:
            d.showpage_url = a["href"]

    return d


def parse_torrent_block(node: Tag) -> TorrentInfo | None:
    text = normalize_text(node.get_text(" ", strip=True))
    if not text:
        return None
    name = ""
    m = re.search(r"Posted on\s+(.+?)\s+by\s+(.+?)(?:\s+Size:|$)", text)
    posted = poster = None
    if m:
        posted = m.group(1).strip()
        poster = m.group(2).strip()
    size_m = re.search(r"Size:\s*([\d.]+\s*[KMGT]?i?B)", text, re.IGNORECASE)
    size = size_m.group(1) if size_m else None
    seeds_m = re.search(r"Seeds:\s*(\d+)", text, re.IGNORECASE)
    peers_m = re.search(r"Peers:\s*(\d+)", text, re.IGNORECASE)
    dl_m = re.search(r"Downloads:\s*(\d+)", text, re.IGNORECASE)
    hash_m = re.search(r"Hash:\s*([a-f0-9]+)", text, re.IGNORECASE)
    a = node.find("a", href=True)
    return TorrentInfo(
        name=name,
        size=size,
        seeds=int(seeds_m.group(1)) if seeds_m else None,
        peers=int(peers_m.group(1)) if peers_m else None,
        downloads=int(dl_m.group(1)) if dl_m else None,
        poster=poster,
        posted=posted,
        hash=hash_m.group(1) if hash_m else None,
        url=a["href"] if a else None,
    )


def parse_torrent_table(table: Tag) -> TorrentInfo | None:
    rows = table.find_all("tr")
    if not rows:
        return None
    cells = rows[0].find_all(["td", "th"])
    text = normalize_text(table.get_text(" ", strip=True))
    a = table.find("a", href=True)
    return TorrentInfo(
        name=normalize_text(a.get_text(" ", strip=True)) if a else text[:80],
        url=a["href"] if a else None,
    )


# ──────────────────────────────────────────────────────────────────────────────
# DB comparison
# ──────────────────────────────────────────────────────────────────────────────

def fetch_db_row(cur: psycopg.Cursor, gid: int) -> dict[str, Any] | None:
    cur.execute("""
        SELECT gid, token, category, title, title_jpn, base_title, uploader,
               posted_at, language, pages, rating, fav_count, comment_count,
               thumb, tags, last_synced_at, is_active
        FROM eh_galleries WHERE gid = %s
    """, (gid,))
    row = cur.fetchone()
    if not row:
        return None
    cols = [desc[0] for desc in cur.description]
    return dict(zip(cols, row))


def diff_field(name: str, db_val: Any, live_val: Any) -> tuple[bool, str]:
    """Return (is_diff, human-readable line)."""
    def fmt(v: Any) -> str:
        if v is None:
            return "NULL"
        if isinstance(v, (list, dict)):
            return json.dumps(v, ensure_ascii=False, default=str)[:120]
        s = str(v)
        if len(s) > 120:
            s = s[:117] + "..."
        return s

    a = fmt(db_val)
    b = fmt(live_val)
    diff = a != b
    return diff, f"  {'DIFF' if diff else 'OK  '} {name:18} db={a:40} live={b}"


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gid", type=int, default=0,
                        help="Specific gid to fetch (default: random synced row)")
    parser.add_argument("--base-url", default=os.getenv("EX_BASE_URL", "https://exhentai.org"))
    parser.add_argument("--proxy", default=os.getenv("PROXY_URL", ""),
                        help="HTTP proxy URL (e.g. http://192.168.0.110:7890)")
    parser.add_argument("--database-url",
                        default=os.getenv("DATABASE_URL",
                                          "postgresql://postgres:postgres@192.168.0.110:5432/eh_stash"))
    parser.add_argument("--save-html", default="", help="Save raw detail HTML to this path")
    args = parser.parse_args()

    cookies = parse_cookie_string(os.getenv("EX_COOKIES", ""))
    if not cookies:
        print("[WARN] no EX_COOKIES in env — exhentai will likely return sad panda", file=sys.stderr)

    # ── Pick a gid ──
    with psycopg.connect(args.database_url) as conn:
        with conn.cursor() as cur:
            gid = args.gid
            if gid == 0:
                cur.execute("""
                    SELECT gid FROM eh_galleries
                    WHERE last_synced_at IS NOT NULL
                    ORDER BY RANDOM() LIMIT 1
                """)
                row = cur.fetchone()
                if not row:
                    print("[ERR] no synced galleries in DB", file=sys.stderr)
                    return 1
                gid = row[0]
                print(f"[INFO] picked random gid={gid}")
            else:
                print(f"[INFO] using requested gid={gid}")

            db_row = fetch_db_row(cur, gid)
            if not db_row:
                print(f"[ERR] gid={gid} not found in eh_galleries", file=sys.stderr)
                return 1
            token = db_row["token"]

    # ── Fetch detail page ──
    url = f"{args.base_url.rstrip('/')}/g/{gid}/{token}/"
    print(f"[FETCH] {url}")
    proxies = {"http": args.proxy, "https": args.proxy} if args.proxy else None
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": args.base_url,
    }
    with Session(headers=headers, cookies=cookies, allow_redirects=True,
                 timeout=30, impersonate="chrome", verify=False,
                 proxies=proxies) as client:
        resp = client.get(url)
        print(f"[FETCH] HTTP {resp.status_code}, {len(resp.text)} bytes")
        if resp.status_code != 200:
            print(f"[ERR] non-200 response; first 200 chars: {resp.text[:200]}", file=sys.stderr)
            return 1
        html = resp.text

    if args.save_html:
        with open(args.save_html, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"[INFO] saved raw HTML to {args.save_html}")

    if "Sad Panda" in html or (len(html) < 200 and "<" not in html):
        print("[ERR] sad panda / blank response — check cookies", file=sys.stderr)
        return 1

    # ── Parse ──
    live = parse_full_detail(html)

    # ── Diff against DB ──
    print("\n" + "=" * 80)
    print(f"DIFF: gid={gid}  title={live.title or db_row['title']}")
    print("=" * 80)

    diffs: list[str] = []
    def compare(name: str, db_val: Any, live_val: Any) -> None:
        is_diff, line = diff_field(name, db_val, live_val)
        print(line)
        if is_diff:
            diffs.append(name)

    compare("title",       db_row["title"],       live.title)
    compare("title_jpn",   db_row["title_jpn"],   live.title_jpn)
    compare("category",    db_row["category"],    live.category)
    compare("uploader",    db_row["uploader"],    live.uploader)
    compare("posted_at",   db_row["posted_at"],   live.posted)
    compare("language",    db_row["language"],    live.language)
    compare("pages",       db_row["pages"],        live.pages)
    compare("rating",      db_row["rating"],       live.rating)
    compare("fav_count",   db_row["fav_count"],    live.fav_count)
    compare("comment_count", db_row["comment_count"], live.comment_count)
    compare("thumb",       db_row["thumb"],        live.thumb)

    # Tags: structural compare (string compare is fooled by key ordering / truncation)
    db_tags = db_row["tags"] or {}
    live_tags_norm = {k: list(v) for k, v in live.tags.items()}
    tags_match = (set(db_tags.keys()) == set(live_tags_norm.keys())
                  and all(set(db_tags.get(k, [])) == set(live_tags_norm.get(k, []))
                          for k in db_tags))
    print(f"  {'OK  ' if tags_match else 'DIFF'} tags (structural)   "
          f"db_ns={sorted(db_tags.keys())} live_ns={sorted(live_tags_norm.keys())} "
          f"db_total={sum(len(v) for v in db_tags.values())} "
          f"live_total={sum(len(v) for v in live_tags_norm.values())}")
    if not tags_match:
        diffs.append("tags")
        for k in set(db_tags.keys()) ^ set(live_tags_norm.keys()):
            side = "only_in_db" if k in db_tags else "only_in_live"
            print(f"    {side}: namespace={k}")
        for k in db_tags.keys() & live_tags_norm.keys():
            missing = set(db_tags[k]) - set(live_tags_norm[k])
            extra = set(live_tags_norm[k]) - set(db_tags[k])
            if missing or extra:
                print(f"    namespace={k}: missing_in_live={sorted(missing)} extra_in_live={sorted(extra)}")

    # ── Surface fields the DB does NOT store at all ──
    print("\n" + "-" * 80)
    print("FIELDS ON PAGE BUT NOT IN eh_galleries SCHEMA:")
    print("-" * 80)

    wasted: list[tuple[str, Any]] = [
        ("rating_count",   live.rating_count),
        ("parent_url",     live.parent_url),
        ("visible",        live.visible),
        ("file_size",      live.file_size),
        ("uploader_url",   live.uploader_url),
        ("archiver_url",   live.archiver_url),
        ("torrent_count",  live.torrent_count),
        ("expunge_petition",  live.expunge_petition_url),
        ("rename_petition",   live.rename_petition_url),
        ("is_deleted",     live.is_deleted),
        ("comments_sample", live.comments[:3]),
        ("page_previews_count", len(live.page_previews)),
        ("tag_entries_with_power", len(live.tag_entries)),
    ]
    for name, val in wasted:
        if isinstance(val, list) and val and isinstance(val[0], CommentInfo):
            shown = [{"author": c.author, "posted": c.posted, "score": c.score,
                      "text": c.text[:80]} for c in val]
            print(f"  {name:28} = {json.dumps(shown, ensure_ascii=False, default=str)[:200]}")
        else:
            v = json.dumps(val, ensure_ascii=False, default=str) if not isinstance(val, (str, int, bool, type(None))) else val
            print(f"  {name:28} = {v}")

    # Tag power breakdown
    if live.tag_entries:
        weak = sum(1 for t in live.tag_entries if t.power == "weak")
        strong = sum(1 for t in live.tag_entries if t.power == "strong")
        unknown = sum(1 for t in live.tag_entries if t.power == "")
        print(f"  tag_power_breakdown       = weak={weak} strong={strong} unknown={unknown}")

    # Torrents sample
    if live.torrents:
        print(f"\n  torrents sample:")
        for t in live.torrents[:3]:
            print(f"    size={t.size} seeds={t.seeds} peers={t.peers} dl={t.downloads} "
                  f"poster={t.poster} hash={t.hash} url={t.url}")

    # ── Summary ──
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"  fields_differs_in_db     = {diffs}")
    print(f"  fields_not_in_db_at_all  = {[n for n, _ in wasted]}")
    print(f"\n  → detail page cost: 1 expensive request")
    print(f"  → currently saved fields: 12 (title/title_jpn/category/uploader/posted/language/pages/rating/fav_count/comment_count/thumb/tags)")
    print(f"  → wasted fields: {len(wasted)} (rating_count, parent_url, visible, file_size, torrents, comments content, page previews, tag power, archiver_url, ...)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
