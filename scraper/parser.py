import re
from bs4 import BeautifulSoup, Tag

GID_TOKEN_RE = re.compile(r"/g/(\d+)/([a-f0-9]+)/")
NEXT_CURSOR_RE = re.compile(r'[?&]next=(\d+)')

def parse_gallery_list(html: str) -> tuple[list[tuple[int, str, str]], int | None]:
    """
    解析列表页 HTML
    返回 (items, next_gid)
      items    = [(gid, token, title), ...]
      next_gid = 下一页游标 GID，None 表示已到最后一页
    """
    soup = BeautifulSoup(html, "lxml")
    results: list[tuple[int, str, str]] = []

    itg = soup.find(class_="itg")
    if not itg:
        return results, None

    for element in itg.find_all(recursive=False):
        glname = element.find(class_="glname")
        if not glname:
            continue

        # 找到 <a> 链接
        a = glname.find("a")
        if a is None:
            parent = glname.parent
            if parent and parent.name == "a":
                a = parent
        if a is None:
            continue

        href = a.get("href", "")
        m = GID_TOKEN_RE.search(href)
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

    # 从分页栏提取下一页游标
    # ExHentai 分页: id="dnext" 为"下一页"按钮，href 含 next=<gid>
    next_gid: int | None = None
    dnext = soup.find(id="dnext")
    if dnext:
        href = dnext.get("href", "")
        m = NEXT_CURSOR_RE.search(href)
        if m:
            next_gid = int(m.group(1))

    return results, next_gid


def parse_detail(html: str) -> dict:
    """
    解析画廊详情页 HTML，返回字段 dict。
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
    
    # 封面 URL
    gd1 = gm.find(id="gd1")
    if gd1:
        div = gd1.find("div")
        if div:
            style = div.get("style", "")
            m = re.search(r"url\((.+?)\)", style)
            if m:
                data["thumb"] = m.group(1).strip("'\"")

    # 详情表格 #gdd
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
                idx = value.find(" ")
                if idx >= 0:
                    try:
                        data["pages"] = int(value[:idx].replace(",", ""))
                    except ValueError:
                        pass
            elif key.startswith("Favorited"):
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
                            
    # Comment count
    cdiv = soup.find(id="cdiv")
    if cdiv:
        aall = cdiv.find(id="aall")
        if aall:
            m = re.search(r"(\d+)", aall.get_text())
            data["comment_count"] = int(m.group(1)) if m else len(cdiv.find_all(class_="c1"))
        else:
            data["comment_count"] = len(cdiv.find_all(class_="c1"))
    else:
        data["comment_count"] = 0

    # Tags extraction
    taglist = soup.find(id="taglist")
    if taglist:
        tags = {}
        # Each row in table inside taglist represents a namespace? Not always.
        # Actually structure is usually <table><tr><td>namespace:</td><td><div><a>tag</a></div>...</td></tr>...</table>
        for tr in taglist.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 2:
                continue
            # namespace like 'language:', 'female:', or empty for misc
            ns_text = tds[0].get_text(strip=True).rstrip(":")
            namespace = ns_text if ns_text else "misc"
            
            tag_values = []
            for div in tds[1].find_all("div"):
                a = div.find("a")
                if a:
                    t = a.get_text(strip=True)
                    # sometimes tags have space or _
                    tag_values.append(t)
            
            if tag_values:
                tags[namespace] = tag_values
        data["tags"] = tags

    return data
