"""SSRF-hardened Playwright browser tool."""
from __future__ import annotations

import ipaddress
import re
from typing import Optional
from urllib.parse import urlparse


PRIVATE_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local / metadata
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]

BLOCKED_HOSTNAMES = {
    "localhost", "metadata.google.internal", "metadata.google.com",
    "169.254.169.254", "0.0.0.0",
}


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if host in BLOCKED_HOSTNAMES:
        raise ValueError(f"Blocked host: {host}")
    try:
        addr = ipaddress.ip_address(host)
        for net in PRIVATE_RANGES:
            if addr in net:
                raise ValueError(f"Blocked private IP: {host}")
    except ValueError as e:
        if "Blocked" in str(e):
            raise
        # Non-IP hostname — allow (DNS resolution happens at browser level)


class BrowserTool:
    """Playwright async browser with SSRF protection."""

    def __init__(self):
        self._browser = None
        self._page = None
        self._playwright = None

    async def __aenter__(self):
        try:
            from playwright.async_api import async_playwright
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
            )
            self._page = await self._browser.new_page()
        except Exception as e:
            raise RuntimeError(f"Playwright not available: {e}. Run: playwright install chromium")
        return self

    async def __aexit__(self, *_):
        try:
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception:
            pass

    async def navigate(self, url: str) -> None:
        _validate_url(url)
        await self._page.goto(url, wait_until="domcontentloaded", timeout=30000)

    async def get_text(self) -> str:
        """Return visible text content of current page."""
        return await self._page.evaluate("""() => {
            const scripts = document.querySelectorAll('script,style,nav,header,footer');
            scripts.forEach(el => el.remove());
            return document.body?.innerText || document.body?.textContent || '';
        }""")

    async def get_html(self) -> str:
        return await self._page.content()

    async def click(self, selector: str) -> None:
        await self._page.click(selector)

    async def fill(self, selector: str, value: str) -> None:
        await self._page.fill(selector, value)

    async def screenshot(self) -> bytes:
        return await self._page.screenshot(type="png")

    async def evaluate(self, js: str) -> object:
        return await self._page.evaluate(js)
