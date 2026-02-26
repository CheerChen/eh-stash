import asyncio
import logging
import json
import random
import sys
from pathlib import Path
from curl_cffi.requests import AsyncSession
from psycopg2.extras import Json

import config
import db
from parser import parse_gallery_list, parse_detail
from logic import decide_fetch_full, decide_fetch_callback

logger = logging.getLogger(__name__)

# ExHentai f_cats bitmask: each bit = a category to EXCLUDE
# To show ONLY one category, exclude all others (ALL_CATS - that_bit)
_ALL_CATS = 1023
_CATEGORY_BITS = {
    'Misc':       1,
    'Doujinshi':  2,
    'Manga':      4,
    'Artist CG':  8,
    'Game CG':    16,
    'Image Set':  32,
    'Cosplay':    64,
    'Asian Porn': 128,
    'Non-H':      256,
    'Western':    512,
}

CATEGORIES = ['Manga', 'Doujinshi', 'Cosplay']

# 全部 6 个 job（scraper- 全量慢轨 + callback- 增量快轨）
ALL_JOBS = (
    [f'scraper-{c.lower()}' for c in CATEGORIES] +
    [f'callback-{c.lower()}' for c in CATEGORIES]
)

async def validate_access(client: AsyncSession) -> bool:
    """Check if we can access the site without Sad Panda or Login errors."""
    url = config.EX_BASE_URL
    logger.info(f"Validating access to {url} ...")

    # Debug: print loaded cookies (mask values for security)
    cookie_keys = list(config.COOKIES.keys())
    cookie_debug = {k: v[:4] + "****" for k, v in config.COOKIES.items()}
    logger.info(f"[DEBUG] Loaded cookie keys: {cookie_keys}")
    logger.info(f"[DEBUG] Cookie preview: {cookie_debug}")

    try:
        resp = await client.get(url, timeout=30)

        logger.info(f"[DEBUG] Response status: {resp.status_code}")
        logger.info(f"[DEBUG] Response URL: {resp.url}")
        logger.info(f"[DEBUG] Response headers: {dict(resp.headers)}")
        logger.info(f"[DEBUG] HTML (first 800 chars):\n{resp.text[:800]}")

        if resp.status_code != 200:
            logger.error(f"Access check failed: HTTP {resp.status_code}")
            return False
            
        # Check for Sad Panda (image or text)
        if "panda.png" in resp.text or "Sad Panda" in resp.text:
            logger.critical("ACCESS DENIED: Sad Panda detected. Check your cookies (ipb_member_id, ipb_pass_hash, sk) in .env")
            return False
            
        # Check for Login requirement
        if "This page requires you to log on" in resp.text or "You must be logged in" in resp.text:
            logger.critical("ACCESS DENIED: Login required. Check your cookies in .env")
            return False

        # The real sad panda page has no navigation ("nb") and no "itg" gallery grid.
        # A logged-in page has id="nb" with real nav links (Front Page, Watched, Popular...).
        # Unauthenticated redirect has no "nb" nav and no gallery content.
        has_nav = 'id="nb"' in resp.text
        has_gallery = 'class="itg"' in resp.text or "itg glte" in resp.text or "itg gltc" in resp.text

        if not has_nav and not has_gallery:
            logger.critical("ACCESS DENIED: No navigation bar or gallery found. Cookies are invalid or expired (Sad Panda).")
            logger.critical(f"HTML Preview: {resp.text[:500]}...")
            return False

        logger.info("Access check passed. Starting loop.")
        return True
    except Exception as e:
        logger.error(f"Access check failed with exception: {e}")
        return False

async def fetch_list_page(client: AsyncSession, category: str, next_gid: int | None = None):
    """
    获取列表页。ExHentai 使用游标分页：
      第一页: ?f_cats=XXX
      后续页: ?f_cats=XXX&next=<gid>
    返回 (items, next_cursor) 或 None（出错时）
    """
    fcats = _ALL_CATS - _CATEGORY_BITS.get(category, 0)
    url = f"{config.EX_BASE_URL}/?f_cats={fcats}"
    if next_gid is not None:
        url += f"&next={next_gid}"
    cursor_label = f"next={next_gid}" if next_gid else "first"
    logger.info(f"[LIST ] {category:<10} {cursor_label:<16} {url}")
    try:
        resp = await client.get(url, timeout=30)
        if resp.status_code != 200:
            logger.warning(f"List page status {resp.status_code}")
            return None
        
        if "panda.png" in resp.text or "Sad Panda" in resp.text:
            logger.error("Sad Panda detected! Your cookies are invalid or IP is banned.")
            return None

        if "This page requires you to log on" in resp.text:
             logger.error("Login required! Please check your cookies.")
             return None

        items, next_cursor = parse_gallery_list(resp.text)
        if not items:
            logger.warning(f"No items found in list page. HTML preview: {resp.text[:500]}...")
            
        return items, next_cursor
    except Exception as e:
        logger.error(f"Error fetching list page: {e}")
        return None

async def fetch_detail(client: AsyncSession, gid: int, token: str):
    url = f"{config.EX_BASE_URL}/g/{gid}/{token}/"
    # logger.info(f"[DETAIL] gid={gid} {url}") 
    # Log handled in loop for consistency
    try:
        resp = await client.get(url, timeout=30)
        if resp.status_code != 200:
            logger.warning(f"Detail page status {resp.status_code}")
            return None
        return parse_detail(resp.text)
    except Exception as e:
        logger.error(f"Error fetching detail: {e}")
        return None

def get_state(job_name):
    with db.get_cursor() as (cur, conn):
        cur.execute("SELECT state FROM schedule_state WHERE job_name = %s", (job_name,))
        row = cur.fetchone()
        state = row[0] if (row and row[0]) else {"next_gid": None, "round": 0}
        # Migrate old state formats
        if "round" not in state:
            state["round"] = 0
        if "current_page" in state:
            del state["current_page"]
            state.setdefault("next_gid", None)
            cur.execute(
                "UPDATE schedule_state SET state = %s WHERE job_name = %s",
                (Json(state), job_name)
            )
        if "next_gid" not in state:
            state["next_gid"] = None
        return state


def save_state(job_name, state):
    with db.get_cursor() as (cur, conn):
        cur.execute(
            "UPDATE schedule_state SET state = %s, last_run_at = NOW() WHERE job_name = %s",
            (Json(state), job_name)
        )


def ensure_job_row(job_name):
    """callback- 行在旧 DB 可能不存在，按需插入。"""
    with db.get_cursor() as (cur, conn):
        cur.execute(
            "INSERT INTO schedule_state (job_name, state) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (job_name, Json({"next_gid": None, "round": 0}))
        )


def get_gallery_meta(gid):
    with db.get_cursor() as (cur, conn):
        cur.execute("SELECT fav_count, rating, pages FROM eh_galleries WHERE gid = %s", (gid,))
        return cur.fetchone()

def build_upsert_row(gid, token, detail):
    return (
        gid,
        token,
        detail.get('category'),
        detail.get('title'),
        detail.get('title_jpn'),
        detail.get('uploader'),
        detail.get('posted'),
        detail.get('language'),
        detail.get('pages'),
        detail.get('rating'),
        detail.get('fav_count'),
        detail.get('comment_count', 0),
        detail.get('thumb'),
        Json(detail.get('tags', {})),
    )

async def run_loop():
    logger.info("Starting endless loop (dual-track: scraper- full + callback- incremental)...")

    if any("YOUR_" in v for v in config.COOKIES.values()):
        logger.warning("Default cookies detected in .env! Please update EX_COOKIES with real values.")

    # 确保 callback- 行存在（旧 DB 迁移兼容）
    for cat in CATEGORIES:
        ensure_job_row(f"callback-{cat.lower()}")

    async with AsyncSession(
        headers=config.HEADERS,
        cookies=config.COOKIES,
        allow_redirects=True,
        timeout=30,
        impersonate="chrome",
        verify=False,
    ) as client:

        if not await validate_access(client):
            logger.critical("Startup validation failed. Exiting.")
            sys.exit(1)

        # thumb 下载器独立运行，使用自己的 Session，不参与 round-robin
        asyncio.create_task(run_thumb_loop())

        while True:
            jobs = ALL_JOBS[:]
            random.shuffle(jobs)

            for job_name in jobs:
                is_callback = job_name.startswith("callback-")
                category = job_name.split("-", 1)[1].capitalize()  # manga→Manga

                if is_callback:
                    await _run_callback_job(client, job_name, category)
                else:
                    await _run_scraper_job(client, job_name, category)


# ---------------------------------------------------------------------------
# scraper- 全量慢轨：无条件抓取每一条，不做活跃检测
# ---------------------------------------------------------------------------
async def _run_scraper_job(client: AsyncSession, job_name: str, category: str):
    state = get_state(job_name)
    next_gid = state.get("next_gid")
    round_num = state.get("round", 0)

    result = await fetch_list_page(client, category, next_gid)
    await asyncio.sleep(config.RATE_INTERVAL)

    if result is None:
        return  # 网络错误，不推进游标

    items, next_cursor = result

    if not items:
        # 到达最后一页，重置开始新一轮
        next_round = round_num + 1
        logger.info(f"[SCRAPER] {category} 全量完毕，round {round_num}→{next_round}，重置游标。")
        save_state(job_name, {"next_gid": None, "round": next_round})
        return

    rows_to_upsert = []

    for gid, token, title in items:
        existing = get_gallery_meta(gid)
        should_fetch, reason = decide_fetch_full(existing)

        if should_fetch:
            detail = await fetch_detail(client, gid, token)
            await asyncio.sleep(config.RATE_INTERVAL)
            if detail:
                action = "+INSERT" if not existing else "UPDATE "
                logger.info(f"[SCRAPER] {category:<10} gid={gid} {action} fav={detail.get('fav_count')}")
                rows_to_upsert.append(build_upsert_row(gid, token, detail))
            else:
                logger.warning(f"[SCRAPER] {category:<10} gid={gid} detail fetch failed")

    if rows_to_upsert:
        db.upsert_galleries_bulk(rows_to_upsert)

    save_state(job_name, {"next_gid": next_cursor, "round": round_num})
    if next_cursor is None:
        next_round = round_num + 1
        logger.info(f"[SCRAPER] {category} 末页，round {round_num}→{next_round}。")
        save_state(job_name, {"next_gid": None, "round": next_round})


# ---------------------------------------------------------------------------
# callback- 增量快轨：多页循环 + detail 额度机制
#   - 每 turn 持有 CALLBACK_DETAIL_QUOTA 个 detail 请求额度
#   - 连续 CALLBACK_SKIP_THRESHOLD 次无变化 → 跳过本页剩余，推进下一页
#   - 退出条件：额度耗尽 / 追到 frontier / 到末页
# ---------------------------------------------------------------------------
async def _run_callback_job(client: AsyncSession, job_name: str, category: str):
    scraper_job = f"scraper-{category.lower()}"
    scraper_state = get_state(scraper_job)
    scraper_frontier = scraper_state.get("next_gid")

    # frontier=None → scraper- 未就绪或刚重置，跳过本轮
    if scraper_frontier is None:
        logger.info(f"[CALLBK] {category:<10} scraper- frontier=None，跳过本轮。")
        return

    state = get_state(job_name)
    cursor = state.get("next_gid")       # 当前页游标
    round_num = state.get("round", 0)

    quota = config.CALLBACK_DETAIL_QUOTA  # 本 turn 剩余 detail 额度
    skip_threshold = config.CALLBACK_SKIP_THRESHOLD
    pages_visited = 0
    exit_reason = None

    while quota > 0:
        result = await fetch_list_page(client, category, cursor)
        await asyncio.sleep(config.RATE_INTERVAL)

        if result is None:
            break  # 网络错误，保存当前位置

        items, next_cursor = result
        pages_visited += 1

        if not items:
            exit_reason = "END"
            break

        # 检查是否已辽及 frontier（本页游标 ≤ frontier）
        if cursor is not None and cursor <= scraper_frontier:
            exit_reason = "FRONTIER"
            break

        consecutive_no_change = 0
        page_skipped = False
        rows_to_upsert = []

        for gid, token, title in items:
            if quota <= 0:
                break

            existing = get_gallery_meta(gid)

            # callback 只更新已有记录，新 gid 留给 scraper 发现
            if existing is None:
                logger.debug(f"[CALLBK] {category:<10} gid={gid} SKIP_NEW (scraper 未到达)")
                continue

            should_fetch, reason = decide_fetch_callback(
                existing, consecutive_no_change, skip_threshold
            )

            if not should_fetch:
                logger.info(f"[CALLBK] {category:<10} 连续 {consecutive_no_change} 次无变化，跳过本页剩余。")
                page_skipped = True
                break

            detail = await fetch_detail(client, gid, token)
            await asyncio.sleep(config.RATE_INTERVAL)
            quota -= 1

            if detail:
                old_fav = existing[0]
                new_fav = detail.get("fav_count", 0)
                if old_fav != new_fav:
                    logger.info(f"[CALLBK] {category:<10} gid={gid} UPDATE  fav {old_fav}→{new_fav} (quota={quota})")
                    rows_to_upsert.append(build_upsert_row(gid, token, detail))
                    consecutive_no_change = 0
                else:
                    consecutive_no_change += 1
                    logger.info(f"[CALLBK] {category:<10} gid={gid} NO_CHNG (seq={consecutive_no_change}, quota={quota})")
            else:
                logger.warning(f"[CALLBK] {category:<10} gid={gid} detail fetch failed")

        if rows_to_upsert:
            db.upsert_galleries_bulk(rows_to_upsert)

        # 推进游标到下一页
        cursor = next_cursor

        # 检查退出条件
        if cursor is None:
            exit_reason = "END"
            break
        if cursor <= scraper_frontier:
            exit_reason = "FRONTIER"
            break
        if quota <= 0:
            exit_reason = "QUOTA"
            break
        # page_skipped → 跳到下一页继续，不退出

    # 决定保存状态
    if exit_reason in ("FRONTIER", "END"):
        # 追上或到末页 → 重置，等下次从最新页重新追
        logger.info(f"[CALLBK] {category} {exit_reason} → 重置游标 (pages={pages_visited}, quota_left={quota})")
        save_state(job_name, {"next_gid": None, "round": round_num + 1})
    else:
        # QUOTA 耗尽或网络错误 → 保存当前位置，下次继续
        logger.info(f"[CALLBK] {category} {exit_reason or 'ERROR'} → 保存位置 cursor={cursor} (pages={pages_visited}, quota_left={quota})")
        save_state(job_name, {"next_gid": cursor, "round": round_num})


# ---------------------------------------------------------------------------
# thumb 下载器：独立运行，不参与 round-robin
#   - 每轮 diff(DB, 本地文件)，下载差集
#   - 差集为空时 sleep 30s；有差集时持续追赶，不额外 sleep
# ---------------------------------------------------------------------------
async def run_thumb_loop():
    thumb_dir = Path(config.THUMB_DIR)
    thumb_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"[THUMB ] 启动，目录={thumb_dir}")

    async with AsyncSession(
        headers=config.HEADERS,
        cookies=config.COOKIES,
        allow_redirects=True,
        timeout=15,
        impersonate="chrome",
        verify=False,
    ) as client:
        while True:
            try:
                all_thumbs = db.get_all_thumb_urls()          # {gid: url}
                local_gids = {int(p.stem) for p in thumb_dir.iterdir() if p.stem.isdigit()}
                missing = {gid: url for gid, url in all_thumbs.items() if gid not in local_gids}

                if not missing:
                    logger.debug(f"[THUMB ] 已全部同步 ({len(local_gids)} 张)，sleep 30s")
                    await asyncio.sleep(30)
                    continue

                logger.info(f"[THUMB ] 差集 {len(missing)} 张，开始下载")

                for gid, url in missing.items():
                    try:
                        resp = await client.get(
                            url,
                            timeout=15,
                            headers={"Referer": "https://exhentai.org/"},
                        )
                        if resp.status_code == 200:
                            dest = thumb_dir / str(gid)
                            dest.write_bytes(resp.content)
                            logger.debug(f"[THUMB ] gid={gid} OK ({len(resp.content)} B)")
                        else:
                            logger.warning(f"[THUMB ] gid={gid} HTTP {resp.status_code}")
                    except Exception as e:
                        logger.warning(f"[THUMB ] gid={gid} 下载失败: {e}")

                    await asyncio.sleep(config.THUMB_RATE_INTERVAL)

            except Exception as e:
                logger.error(f"[THUMB ] 循环异常: {e}")
                await asyncio.sleep(10)
