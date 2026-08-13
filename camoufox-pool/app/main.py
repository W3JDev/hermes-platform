"""camoufox-pool: anti-detect headless browser service for Hermes Platform.

Wraps Camoufox (Firefox with anti-fingerprinting) in a small FastAPI HTTP API.
Used by all Hermes profiles for browser automation that bypasses bot detection.
"""
import os
import asyncio
import base64
import logging
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("camoufox-pool")

CAMOUFOX_VERSION = "0.4.10"


class NavRequest(BaseModel):
    url: str
    fingerprint: Optional[str] = "windows_chrome"
    full_page: Optional[bool] = True
    wait_ms: Optional[int] = 1000


class ExtractRequest(BaseModel):
    url: str
    selector: str
    fingerprint: Optional[str] = "windows_chrome"
    wait_ms: Optional[int] = 1000


class ScreenshotRequest(BaseModel):
    url: str
    full_page: Optional[bool] = True
    fingerprint: Optional[str] = "windows_chrome"
    wait_ms: Optional[int] = 1000


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"[camoufox-pool] Starting up, version={CAMOUFOX_VERSION}")
    yield
    logger.info("[camoufox-pool] Shutting down")


app = FastAPI(title="camoufox-pool", lifespan=lifespan)


async def _take_screenshot(req) -> bytes:
    """Use camoufox to navigate and take a screenshot."""
    try:
        from camoufox.async_api import AsyncCamoufox
    except ImportError as e:
        logger.error(f"[camoufox-pool] camoufox not importable: {e}")
        raise HTTPException(status_code=503, detail=f"camoufox not available: {e}")

    try:
        async with AsyncCamoufox(headless=True) as browser:
            page = await browser.new_page()
            await page.goto(req.url, wait_until="domcontentloaded", timeout=30000)
            if req.wait_ms:
                await page.wait_for_timeout(req.wait_ms)
            screenshot = await page.screenshot(full_page=req.full_page)
            await page.close()
            return screenshot
    except Exception as e:
        logger.exception("[camoufox-pool] screenshot failed")
        raise HTTPException(status_code=500, detail=f"screenshot failed: {str(e)[:200]}")


@app.get("/health")
async def health():
    return {"ok": True, "camoufox_version": CAMOUFOX_VERSION, "service": "camoufox-pool"}


@app.post("/screenshot")
async def screenshot(req: ScreenshotRequest):
    """Take a screenshot of a URL. Returns PNG bytes (base64-encoded in JSON)."""
    png = await _take_screenshot(req)
    return {"ok": True, "format": "png", "size_bytes": len(png), "data_base64": base64.b64encode(png).decode("ascii")}


@app.post("/navigate")
async def navigate(req: NavRequest):
    """Navigate to a URL and return a screenshot."""
    png = await _take_screenshot(req)
    return {"ok": True, "url": req.url, "format": "png", "size_bytes": len(png), "data_base64": base64.b64encode(png).decode("ascii")}


@app.post("/extract")
async def extract(req: ExtractRequest):
    """Extract text from a URL by CSS selector."""
    try:
        from camoufox.async_api import AsyncCamoufox
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"camoufox not available: {e}")

    try:
        async with AsyncCamoufox(headless=True) as browser:
            page = await browser.new_page()
            await page.goto(req.url, wait_until="domcontentloaded", timeout=30000)
            if req.wait_ms:
                await page.wait_for_timeout(req.wait_ms)
            elements = await page.query_selector_all(req.selector)
            texts = []
            for el in elements[:50]:
                txt = await el.text_content()
                if txt:
                    texts.append(txt.strip())
            await page.close()
            return {"ok": True, "url": req.url, "selector": req.selector, "count": len(texts), "texts": texts}
    except Exception as e:
        logger.exception("[camoufox-pool] extract failed")
        raise HTTPException(status_code=500, detail=f"extract failed: {str(e)[:200]}")
