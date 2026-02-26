"""
Pure (side-effect-free) business logic for the scraper.
No network, no DB, no external dependencies — easily unit-testable.
"""


def decide_fetch_full(existing) -> tuple[bool, str]:
    """
    scraper- 全量模式：无条件抓取每一条。
    Returns (should_fetch, reason).
    """
    if existing is None:
        return True, "NEW"
    return True, "FULL"


def decide_fetch_callback(existing, consecutive_no_change: int, threshold: int) -> tuple[bool, str]:
    """
    callback- 增量模式：新记录必抓；连续无变化达到阈值则跳过。
    Returns (should_fetch, reason).
    """
    if existing is None:
        return True, "NEW"
    if consecutive_no_change >= threshold:
        return False, "SKIP"
    return True, "CHECK"
