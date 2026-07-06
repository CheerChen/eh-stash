"""Proxy controller: monitors ban events and switches mihomo nodes.

Architecture:
  - Scraper writes `proxy.banned` events to sync_task_events on ban detection.
  - This controller polls sync_task_events every few seconds for new ban events.
  - On a new ban event, it scans mihomo candidate nodes (SELECT group),
    probing each with a cookie-authenticated request to exhentai.
  - If a healthy node is found, it switches mihomo's SELECT to that node.
  - If all nodes are banned, it logs and waits (cooldown to avoid storm).
  - Scraper's exponential backoff will detect the recovery on its next probe.

The controller is a singleton started once at app startup via start_worker().
"""

import asyncio
import os
import time
import logging
import httpx
import psycopg2
from typing import Optional

from db import connection_pool

logger = logging.getLogger("proxy_controller")

MIHOMO_API = os.getenv("MIHOMO_API", "")
PROXY_URL = os.getenv("PROXY_URL", "")
EX_COOKIES = os.getenv("EX_COOKIES", "")
EX_BASE_URL = os.getenv("EX_BASE_URL", "https://exhentai.org")

# Cooldown between scans to avoid event storms (scraper sends ban events
# every ~30s while banned). Once we scan, we don't scan again for this long.
SCAN_COOLDOWN_SEC = 300  # 5 minutes

# Poll interval for checking new ban events in sync_task_events.
POLL_INTERVAL_SEC = 5

# Per-node probe timeout.
PROBE_TIMEOUT_SEC = 12

# SELECT group name in mihomo (the top-level selector).
SELECT_GROUP = "SELECT"


class ProxyState:
    """In-memory state of the proxy controller, shared with the router."""

    def __init__(self):
        self.current_node: Optional[str] = None
        self.last_scan_at: Optional[float] = None
        self.last_scan_result: Optional[str] = None  # "switched" | "all_banned" | "error"
        self.last_switched_to: Optional[str] = None
        self.last_ban_event_at: Optional[float] = None
        self.last_ban_duration: Optional[int] = None
        self.scan_in_progress: bool = False
        self.scan_history: list[dict] = []  # recent scan results, newest first

    def snapshot(self) -> dict:
        return {
            "current_node": self.current_node,
            "last_scan_at": self.last_scan_at,
            "last_scan_result": self.last_scan_result,
            "last_switched_to": self.last_switched_to,
            "last_ban_event_at": self.last_ban_event_at,
            "last_ban_duration": self.last_ban_duration,
            "scan_in_progress": self.scan_in_progress,
            "scan_history": self.scan_history[:10],
            "mihomo_api": MIHOMO_API or None,
            "proxy_url": PROXY_URL or None,
        }


# Global singleton state
state = ProxyState()


def _parse_cookies(raw: str) -> dict:
    cookies = {}
    for pair in raw.split(";"):
        pair = pair.strip()
        if not pair:
            continue
        k, _, v = pair.partition("=")
        k = k.strip()
        v = v.strip()
        if k:
            cookies[k] = v
    return cookies


async def _mihomo_get_select_nodes(client: httpx.AsyncClient) -> list[str]:
    """Get the list of selectable items in the SELECT group."""
    resp = await client.get(f"{MIHOMO_API}/proxies/{SELECT_GROUP}", timeout=5)
    resp.raise_for_status()
    data = resp.json()
    return data.get("all", [])


async def _mihomo_get_proxy_type(client: httpx.AsyncClient, name: str) -> str:
    """Get the type of a proxy entry (Selector, URLTest, Shadowsocks, etc.)."""
    from urllib.parse import quote
    resp = await client.get(f"{MIHOMO_API}/proxies/{quote(name)}", timeout=5)
    resp.raise_for_status()
    return resp.json().get("type", "")


async def _mihomo_get_urltest_groups(client: httpx.AsyncClient) -> list[str]:
    """Get SELECT children that are URLTest groups (skip Selector groups like NON-JP and DIRECT)."""
    all_nodes = await _mihomo_get_select_nodes(client)
    groups = []
    for name in all_nodes:
        if name == "DIRECT":
            continue
        ptype = await _mihomo_get_proxy_type(client, name)
        if ptype == "URLTest":
            groups.append(name)
    return groups


async def _mihomo_switch(client: httpx.AsyncClient, node: str) -> None:
    """Switch the SELECT group to the given node."""
    resp = await client.put(
        f"{MIHOMO_API}/proxies/{SELECT_GROUP}",
        json={"name": node},
        timeout=5,
    )
    resp.raise_for_status()


async def _mihomo_get_current(client: httpx.AsyncClient) -> Optional[str]:
    """Get the currently selected node in the SELECT group."""
    resp = await client.get(f"{MIHOMO_API}/proxies/{SELECT_GROUP}", timeout=5)
    resp.raise_for_status()
    return resp.json().get("now")


async def _probe_node(client: httpx.AsyncClient, node: str, cookies: dict) -> str:
    """Probe exhentai through a specific mihomo node.

    Returns:
      "ok"       — site responds normally (200 + content)
      "banned"   — ban page detected
      "error"    — inconclusive (timeout, connection error, etc.)
    """
    await _mihomo_switch(client, node)
    await asyncio.sleep(0.5)  # let mihomo pick up the switch

    try:
        resp = await client.get(
            EX_BASE_URL,
            cookies=cookies,
            timeout=PROBE_TIMEOUT_SEC,
            follow_redirects=False,
        )
    except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPError) as e:
        logger.warning(f"probe {node}: error {e}")
        return "error"

    if resp.status_code != 200:
        logger.warning(f"probe {node}: HTTP {resp.status_code}")
        return "error"

    body = resp.text
    if "temporarily banned" in body or "IP address has been" in body:
        logger.info(f"probe {node}: banned")
        return "banned"

    if len(body) > 100 and ("front_page" in body or "itg" in body):
        logger.info(f"probe {node}: ok")
        return "ok"

    logger.warning(f"probe {node}: inconclusive (status={resp.status_code} len={len(body)})")
    return "error"


async def scan_and_switch() -> dict:
    """Scan candidate nodes and switch to the first healthy one.

    Returns a dict with scan result details.
    """
    if not MIHOMO_API or not PROXY_URL or not EX_COOKIES:
        result = {"error": "MIHOMO_API, PROXY_URL, or EX_COOKIES not configured"}
        logger.warning(result["error"])
        state.last_scan_result = "error"
        state.scan_history.insert(0, result)
        return result

    if state.scan_in_progress:
        result = {"error": "scan already in progress"}
        return result

    state.scan_in_progress = True
    start_time = time.time()

    try:
        cookies = _parse_cookies(EX_COOKIES)
        async with httpx.AsyncClient(proxy=PROXY_URL) as proxy_client:
            # Use a separate client for mihomo API (no proxy needed)
            async with httpx.AsyncClient() as mihomo_client:
                # Refresh current node
                state.current_node = await _mihomo_get_current(mihomo_client)

                nodes = await _mihomo_get_urltest_groups(mihomo_client)
                logger.info(f"scan started: {len(nodes)} URLTest groups, current={state.current_node}")

                results = []
                switched_to = None

                for node in nodes:
                    status = await _probe_node(proxy_client, node, cookies)
                    results.append({"node": node, "status": status})
                    if status == "ok":
                        switched_to = node
                        break

                elapsed = time.time() - start_time
                result = {
                    "scanned": len(results),
                    "results": results,
                    "switched_to": switched_to,
                    "elapsed_sec": round(elapsed, 1),
                    "timestamp": time.time(),
                }

                if switched_to:
                    state.last_scan_result = "switched"
                    state.last_switched_to = switched_to
                    state.current_node = switched_to
                    logger.info(f"scan complete: switched to {switched_to} in {elapsed:.1f}s")
                else:
                    state.last_scan_result = "all_banned"
                    logger.warning(f"scan complete: all nodes banned/unreachable in {elapsed:.1f}s")

                state.scan_history.insert(0, result)
                state.last_scan_at = time.time()
                return result

    except Exception as e:
        result = {"error": str(e), "timestamp": time.time()}
        state.last_scan_result = "error"
        state.scan_history.insert(0, result)
        logger.error(f"scan failed: {e}")
        return result
    finally:
        state.scan_in_progress = False


def _fetch_latest_ban_event() -> Optional[dict]:
    """Check for recent proxy.banned events in sync_task_events.

    Returns the latest ban event if there's a new one since last check,
    or None if no new ban events.
    """
    conn = connection_pool.getconn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, event_type, message, payload, created_at
            FROM sync_task_events
            WHERE event_type = 'proxy.banned'
            ORDER BY id DESC
            LIMIT 1
            """,
        )
        row = cur.fetchone()
        if not row:
            return None
        event_id, event_type, message, payload, created_at = row
        return {
            "id": event_id,
            "event_type": event_type,
            "message": message,
            "payload": payload or {},
            "created_at": created_at,
        }
    finally:
        cur.close()
        connection_pool.putconn(conn)


async def _worker_loop():
    """Background worker: poll for ban events and trigger scan_and_switch."""
    logger.info("proxy controller worker started")
    last_seen_event_id = 0

    # Initialize: fetch current mihomo state
    if MIHOMO_API:
        try:
            async with httpx.AsyncClient() as client:
                state.current_node = await _mihomo_get_current(client)
                logger.info(f"proxy controller initialized, current node: {state.current_node}")
        except Exception as e:
            logger.warning(f"failed to get initial mihomo state: {e}")

    while True:
        try:
            event = _fetch_latest_ban_event()
            if event and event["id"] > last_seen_event_id:
                last_seen_event_id = event["id"]
                state.last_ban_event_at = time.time()
                payload = event.get("payload") or {}
                state.last_ban_duration = payload.get("duration_secs")

                logger.info(
                    f"ban event detected (id={event['id']}), "
                    f"duration={state.last_ban_duration}s"
                )

                # Check cooldown: don't scan if we scanned recently
                if state.last_scan_at and (time.time() - state.last_scan_at) < SCAN_COOLDOWN_SEC:
                    remaining = SCAN_COOLDOWN_SEC - (time.time() - state.last_scan_at)
                    logger.info(f"scan cooldown active, skipping (remaining {remaining:.0f}s)")
                else:
                    await scan_and_switch()

        except Exception as e:
            logger.error(f"worker loop error: {e}")

        await asyncio.sleep(POLL_INTERVAL_SEC)


def start_worker():
    """Start the proxy controller background worker."""
    if not MIHOMO_API:
        logger.warning("MIHOMO_API not set, proxy controller disabled")
        return
    asyncio.create_task(_worker_loop())
