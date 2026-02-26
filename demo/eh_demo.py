# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "curl-cffi",
#   "beautifulsoup4",
#   "lxml",
# ]
# ///
"""
EH Gallery Scraper Demo
- 每秒抓取 1 页列表，共 10 页
- 逐个抓取 detail 页（每秒 1 个），存入内存
- 按 fav_count 降序排序，输出到 CSV
"""

import asyncio
import csv
import re
from dataclasses import asdict, dataclass

from bs4 import BeautifulSoup, Tag
from curl_cffi.requests import AsyncSession

# ──────────────────────────────────────────────
# 配置
# ──────────────────────────────────────────────
BASE_URL = "https://e-hentai.org"
LIST_URL = BASE_URL + "/?f_search=language%3Achinese+language%3Atranslated&page={page}"
DETAIL_URL = BASE_URL + "/g/{gid}/{token}/"
LIST_PAGES = 1            # 只抓第 1 页（25 条）
LIST_INTERVAL = 1.0       # 列表页间隔（秒）
DETAIL_INTERVAL = 1.0     # detail 页间隔（秒）
OUTPUT_CSV = "galleries.csv"

# 如需登录（抓 EX 或敏感内容），填入 Cookie
COOKIES: dict[str, str] = {
    # "ipb_member_id": "YOUR_ID",
    # "ipb_pass_hash": "YOUR_HASH",
    # "sk": "YOUR_SK",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": BASE_URL,
}

GID_TOKEN_RE = re.compile(r"/g/(\d+)/([a-f0-9]+)/")


# ──────────────────────────────────────────────
# 数据模型
# ──────────────────────────────────────────────
@dataclass
class Gallery:
    gid: int
    token: str
    title: str = ""
    title_jpn: str = ""
    category: str = ""
    uploader: str = ""
    posted: str = ""
    language: str = ""
    pages: int = 0
    rating: float = 0.0
    fav_count: int = 0
    thumb: str = ""


# ──────────────────────────────────────────────
# 解析：列表页  →  参考 GalleryListParser.kt
# ──────────────────────────────────────────────
def parse_gallery_list(html: str) -> list[tuple[int, str, str]]:
    """
    返回 [(gid, token, title), ...]
    """
    soup = BeautifulSoup(html, "lxml")
    results: list[tuple[int, str, str]] = []

    itg = soup.find(class_="itg")
    if not itg:
        return results

    for element in itg.find_all(recursive=False):
        glname = element.find(class_="glname")
        if not glname:
            continue

        # 找到 <a> 链接（可能是 glname 内或 glname 的父节点）
        a = glname.find("a")
        if a is None:
            parent = glname.parent
            if parent and parent.name == "a":
                a = parent
        if a is None:
            continue

        m = GID_TOKEN_RE.search(a.get("href", ""))
        if not m:
            continue
        gid, token = int(m.group(1)), m.group(2)

        # 取最深子节点的文本作为标题
        node = glname
        while True:
            tag_children = [c for c in node.children if isinstance(c, Tag)]
            if not tag_children:
                break
            node = tag_children[0]
        title = node.get_text(strip=True) if isinstance(node, Tag) else str(node).strip()

        results.append((gid, token, title))

    return results


# ──────────────────────────────────────────────
# 解析：detail 页  →  参考 GalleryDetailParser.kt
# ──────────────────────────────────────────────
def parse_detail(html: str) -> dict:
    """
    解析画廊详情页，返回字段 dict。
    fav_count 来自 #gdd 表格的 "Favorited" 行。
    """
    soup = BeautifulSoup(html, "lxml")
    data: dict = {}

    gm = soup.find(class_="gm")
    if not gm:
        return data

    # 标题
    gn = gm.find(id="gn")
    data["title"] = gn.get_text(strip=True) if gn else ""
    gj = gm.find(id="gj")
    data["title_jpn"] = gj.get_text(strip=True) if gj else ""

    # 分类  .cn（彩色）或 .cs（灰色）
    ce = gm.find(class_="cn") or gm.find(class_="cs")
    data["category"] = ce.get_text(strip=True) if ce else ""

    # 上传者
    gdn = gm.find(id="gdn")
    data["uploader"] = gdn.get_text(strip=True) if gdn else ""

    # 评分
    rating_label = gm.find(id="rating_label")
    if rating_label:
        rtext = rating_label.get_text(strip=True)
        if "Not Yet Rated" not in rtext:
            idx = rtext.find(" ")
            if idx != -1:
                try:
                    data["rating"] = float(rtext[idx + 1:])
                except ValueError:
                    pass

    # 封面 URL（gd1 style 中的 url(...)）
    gd1 = gm.find(id="gd1")
    if gd1:
        div = gd1.find("div")
        if div:
            style = div.get("style", "")
            m = re.search(r"url\((.+?)\)", style)
            if m:
                data["thumb"] = m.group(1).strip("'\"")

    # 详情表格 #gdd  →  Posted / Language / Length / Favorited
    gdd = gm.find(id="gdd")
    if gdd:
        for tr in gdd.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 2:
                continue
            key = tds[0].get_text(strip=True)
            value = tds[1].get_text(strip=True)

            if key.startswith("Posted"):
                data["posted"] = value
            elif key.startswith("Language"):
                data["language"] = value
            elif key.startswith("Length"):
                # "123 pages"
                idx = value.find(" ")
                if idx >= 0:
                    try:
                        data["pages"] = int(value[:idx].replace(",", ""))
                    except ValueError:
                        pass
            elif key.startswith("Favorited"):
                # "Never" | "Once" | "1234 times"
                if value == "Never":
                    data["fav_count"] = 0
                elif value == "Once":
                    data["fav_count"] = 1
                else:
                    idx = value.find(" ")
                    if idx >= 0:
                        try:
                            data["fav_count"] = int(value[:idx].replace(",", ""))
                        except ValueError:
                            data["fav_count"] = 0

    return data


# ──────────────────────────────────────────────
# 网络请求
# ──────────────────────────────────────────────
async def fetch_list_page(
    client: AsyncSession, page: int
) -> list[tuple[int, str, str]]:
    url = LIST_URL.format(page=page)
    print(f"[LIST ] page={page:2d}  {url}")
    resp = await client.get(url)
    resp.raise_for_status()
    items = parse_gallery_list(resp.text)
    print(f"         → {len(items)} galleries")
    return items


async def fetch_detail(
    client: AsyncSession, gid: int, token: str, idx: int, total: int
) -> dict:
    url = DETAIL_URL.format(gid=gid, token=token)
    print(f"[DETAIL] [{idx:4d}/{total}] gid={gid}  {url}")
    resp = await client.get(url)
    resp.raise_for_status()
    return parse_detail(resp.text)


# ──────────────────────────────────────────────
# 主流程
# ──────────────────────────────────────────────
async def main() -> None:
    async with AsyncSession(
        headers=HEADERS,
        cookies=COOKIES,
        allow_redirects=True,
        timeout=30,
        impersonate="chrome",   # 使用 Chrome TLS 指纹，绕过握手兼容问题
        verify=False,           # macOS curl CA bundle 路径问题，demo 不做证书校验
    ) as client:

        # ── Phase 1: 抓列表，每秒一页 ──
        print("=" * 60)
        print(f"Phase 1: 抓取 {LIST_PAGES} 页列表（间隔 {LIST_INTERVAL}s）")
        print("=" * 60)

        all_items: list[tuple[int, str, str]] = []
        for page in range(LIST_PAGES):
            items = await fetch_list_page(client, page)
            all_items.extend(items)
            if page < LIST_PAGES - 1:
                await asyncio.sleep(LIST_INTERVAL)

        print(f"\n共获取 {len(all_items)} 个 gallery\n")

        # ── Phase 2: 逐个抓 detail，每秒一个 ──
        print("=" * 60)
        print(f"Phase 2: 逐个抓取 detail（间隔 {DETAIL_INTERVAL}s）")
        print("=" * 60)

        galleries: list[Gallery] = []
        total = len(all_items)

        for i, (gid, token, fallback_title) in enumerate(all_items, start=1):
            try:
                detail = await fetch_detail(client, gid, token, i, total)
                g = Gallery(
                    gid=gid,
                    token=token,
                    title=detail.get("title") or fallback_title,
                    title_jpn=detail.get("title_jpn", ""),
                    category=detail.get("category", ""),
                    uploader=detail.get("uploader", ""),
                    posted=detail.get("posted", ""),
                    language=detail.get("language", ""),
                    pages=detail.get("pages", 0),
                    rating=detail.get("rating", 0.0),
                    fav_count=detail.get("fav_count", 0),
                    thumb=detail.get("thumb", ""),
                )
                galleries.append(g)
                print(
                    f"         fav={g.fav_count:5d}  rating={g.rating:.1f}"
                    f"  {g.title[:45]}"
                )
            except Exception as e:
                status = getattr(getattr(e, "response", None), "status_code", None)
                if status:
                    print(f"         [HTTP ERROR] {status} gid={gid}")
                else:
                    print(f"         [ERROR] gid={gid}: {e}")

            if i < total:
                await asyncio.sleep(DETAIL_INTERVAL)

    # ── Phase 3: 排序 + 保存 CSV ──
    print("\n" + "=" * 60)
    print("Phase 3: 按 fav_count 降序排序，写入 CSV")
    print("=" * 60)

    galleries.sort(key=lambda g: g.fav_count, reverse=True)

    fieldnames = [
        "gid", "token", "title", "title_jpn", "category",
        "uploader", "posted", "language", "pages", "rating",
        "fav_count", "thumb",
    ]
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for g in galleries:
            writer.writerow(asdict(g))

    print(f"\n已保存 {len(galleries)} 条数据 → {OUTPUT_CSV}")
    print("\nTop 10 by fav_count:")
    print(f"{'fav':>6}  {'rating':>6}  {'category':<12}  title")
    print("-" * 70)
    for g in galleries[:10]:
        print(f"{g.fav_count:6d}  {g.rating:6.1f}  {g.category:<12}  {g.title[:40]}")


if __name__ == "__main__":
    asyncio.run(main())