"""Proxy management endpoints for the admin API.

Provides visibility into the proxy controller state and allows manual
triggering of node scans and switches.
"""

import asyncio
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from proxy_controller import state, scan_and_switch

router = APIRouter(prefix="/v1/admin/proxy", tags=["proxy"])


class SwitchRequest(BaseModel):
    node: str


@router.get("/status")
def proxy_status():
    """Return the current proxy controller state."""
    return state.snapshot()


@router.post("/scan")
async def proxy_scan():
    """Manually trigger a node scan and switch."""
    result = await scan_and_switch()
    return result


@router.post("/switch")
async def proxy_switch(req: SwitchRequest):
    """Manually switch the SELECT group to a specific node."""
    from proxy_controller import MIHOMO_API, _mihomo_switch, _mihomo_get_current
    import httpx

    if not MIHOMO_API:
        raise HTTPException(status_code=503, detail="MIHOMO_API not configured")

    try:
        async with httpx.AsyncClient() as client:
            await _mihomo_switch(client, req.node)
            state.current_node = await _mihomo_get_current(client)
            state.last_switched_to = req.node
            state.last_scan_result = "manual_switch"
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"mihomo API error: {e}")

    return {"switched_to": req.node, "current_node": state.current_node}
