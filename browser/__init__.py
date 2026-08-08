"""
browser/ -- Browser automation with Playwright.

Adapted from Mark's browser control, integrated into VYREN's
tool/agent architecture as a singleton browser session manager.
"""

from __future__ import annotations

import asyncio
import base64
import concurrent.futures
import logging
import platform
import shutil
import threading
from typing import Any, Optional

logger = logging.getLogger("vyren.browser")

try:
    from playwright.async_api import async_playwright, Page
    _PLAYWRIGHT_OK = True
except ImportError:
    _PLAYWRIGHT_OK = False
    async_playwright = None  # type: ignore
    Page = None  # type: ignore


def _get_default_browser_id() -> str:
    system = platform.system()
    try:
        if system == "Windows":
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice",
            )
            prog_id = winreg.QueryValueEx(key, "ProgId")[0].lower()
            winreg.CloseKey(key)
            return prog_id
        elif system == "Darwin":
            import subprocess
            result = subprocess.run(
                ["defaults", "read",
                 "com.apple.LaunchServices/com.apple.launchservices.secure",
                 "LSHandlers"],
                capture_output=True, text=True, timeout=5,
            )
            return result.stdout.lower()
        elif system == "Linux":
            import subprocess
            result = subprocess.run(
                ["xdg-settings", "get", "default-web-browser"],
                capture_output=True, text=True, timeout=5,
            )
            return result.stdout.lower()
    except Exception:
        pass
    return ""


_BROWSER_BINARIES = {
    "Windows": {
        "opera": ["opera.exe"],
        "brave": ["brave.exe"],
        "vivaldi": ["vivaldi.exe"],
        "chrome": ["chrome.exe"],
        "firefox": ["firefox.exe"],
    },
    "Darwin": {
        "opera": ["opera"],
        "brave": ["brave browser", "brave"],
        "vivaldi": ["vivaldi"],
        "chrome": ["google chrome", "google-chrome"],
        "firefox": ["firefox"],
    },
    "Linux": {
        "opera": ["opera", "opera-stable"],
        "brave": ["brave-browser", "brave"],
        "vivaldi": ["vivaldi-stable", "vivaldi"],
        "chrome": ["google-chrome", "google-chrome-stable", "chromium-browser", "chromium"],
        "firefox": ["firefox"],
    },
}


def _get_opera_executable() -> Optional[str]:
    if platform.system() != "Windows":
        return None
    try:
        import winreg
        candidate_keys = [
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\opera.exe",
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\launcher.exe",
            r"SOFTWARE\Clients\StartMenuInternet\OperaStable\shell\open\command",
            r"SOFTWARE\Clients\StartMenuInternet\OperaGXStable\shell\open\command",
        ]
        for key_path in candidate_keys:
            for hive in [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]:
                try:
                    key = winreg.OpenKey(hive, key_path)
                    val = winreg.QueryValue(key, None)
                    winreg.CloseKey(key)
                    exe = val.strip().strip('"').split('"')[0].split(" --")[0].strip()
                    if exe and Path(exe).exists():
                        logger.info("[Browser] Opera found via registry: %s", exe)
                        return exe
                except Exception:
                    continue
    except Exception:
        pass
    return None


def _find_browser_executable(prog_id: str) -> tuple[str, Optional[str], Optional[str], bool]:
    system = platform.system()
    os_bins = _BROWSER_BINARIES.get(system, {})

    if any(x in prog_id for x in ["firefox", "mozilla"]):
        return "firefox", None, None, False
    if "safari" in prog_id:
        return "webkit", None, None, False
    if "edge" in prog_id:
        return "chromium", None, "msedge", False
    if "opera" in prog_id:
        exe = _get_opera_executable()
        if exe:
            return "chromium", exe, None, True
        for binary in os_bins.get("opera", []):
            path = shutil.which(binary)
            if path:
                return "chromium", path, None, True

    browser_patterns = {"brave": ["brave"], "vivaldi": ["vivaldi"], "chrome": ["chrome"]}
    for browser_name, patterns in browser_patterns.items():
        if not any(p in prog_id for p in patterns):
            continue
        for binary in os_bins.get(browser_name, []):
            path = shutil.which(binary)
            if path:
                logger.info("[Browser] Found %s at: %s", browser_name, path)
                return "chromium", path, None, False

    if "chrome" in prog_id or not prog_id:
        return "chromium", None, "chrome", False
    return "chromium", None, None, False


class _BrowserThread:
    def __init__(self) -> None:
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None
        self._engine_name = "chromium"
        self._exe_path: Optional[str] = None
        self._channel: Optional[str] = None
        self._is_opera = False

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            try:
                self._loop.call_soon_threadsafe(self._loop.stop)
                self._thread.join(timeout=5)
            except Exception:
                pass
        self._thread = None
        self._loop = None
        self._ready.clear()
        if not _PLAYWRIGHT_OK:
            raise RuntimeError("playwright is not installed")
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="BrowserThread",
        )
        self._thread.start()
        ok = self._ready.wait(timeout=20)
        if not ok:
            raise RuntimeError("Browser thread did not start within 20s.")

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._init())
        self._ready.set()
        self._loop.run_forever()

    async def _init(self) -> None:
        self._playwright = await async_playwright().start()

    def run(self, coro, timeout: int = 30) -> Any:
        if not self._loop:
            raise RuntimeError("BrowserThread not started.")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    async def _launch_browser_if_needed(self) -> None:
        if self._browser and self._browser.is_connected():
            return
        prog_id = _get_default_browser_id()
        self._engine_name, self._exe_path, self._channel, self._is_opera = _find_browser_executable(prog_id)
        engine = getattr(self._playwright, self._engine_name)

        chromium_args = ["--start-maximized"]
        if self._is_opera:
            chromium_args += ["--disable-features=OperaPrivacyMode", "--no-private"]
            logger.info("[Browser] Opera detected — disabling private-mode flags")

        launch_kwargs = {"headless": False}
        if self._engine_name == "chromium":
            launch_kwargs["args"] = chromium_args
        if self._exe_path:
            launch_kwargs["executable_path"] = self._exe_path
        elif self._channel:
            launch_kwargs["channel"] = self._channel

        try:
            self._browser = await engine.launch(**launch_kwargs)
            logger.info(
                "[Browser] Launched (%s%s%s)",
                self._engine_name,
                f" / {self._channel}" if self._channel else "",
                f" / {self._exe_path}" if self._exe_path else "",
            )
        except Exception as e:
            logger.warning("[Browser] Launch failed (%s), falling back to built-in Chromium", e)
            self._browser = await self._playwright.chromium.launch(
                headless=False, args=["--start-maximized"],
            )

    async def _get_page(self) -> Page:
        await self._launch_browser_if_needed()

        if self._context is None:
            self._context = await self._browser.new_context(
                viewport=None,
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            )

        if self._page is None or self._page.is_closed():
            self._page = await self._context.new_page()

        return self._page

    async def _go_to(self, url: str) -> str:
        if not url.startswith("http"):
            url = "https://" + url
        page = await self._get_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            return f"Opened: {page.url}"
        except concurrent.futures.TimeoutError:
            return f"Timeout loading: {url}"
        except Exception as e:
            return f"Navigation error: {e}"

    async def _search(self, query: str, engine: str = "google") -> str:
        engines = {
            "google": f"https://www.google.com/search?q={query.replace(' ', '+')}",
            "bing": f"https://www.bing.com/search?q={query.replace(' ', '+')}",
            "duckduckgo": f"https://duckduckgo.com/?q={query.replace(' ', '+')}",
        }
        url = engines.get(engine.lower(), engines["google"])
        return await self._go_to(url)

    async def _click(self, selector=None, text=None) -> str:
        page = await self._get_page()
        try:
            if text:
                await page.get_by_text(text, exact=False).first.click(timeout=8000)
                return f"Clicked: '{text}'"
            elif selector:
                await page.click(selector, timeout=8000)
                return f"Clicked: {selector}"
            return "No selector or text provided."
        except concurrent.futures.TimeoutError:
            return "Element not found or not clickable."
        except Exception as e:
            return f"Click error: {e}"

    async def _type(self, selector=None, text: str = "", clear_first: bool = True) -> str:
        page = await self._get_page()
        try:
            element = page.locator(selector).first if selector else page.locator(":focus")
            if clear_first:
                await element.clear()
            await element.type(text, delay=50)
            return "Text typed."
        except Exception as e:
            return f"Type error: {e}"

    async def _scroll(self, direction: str = "down", amount: int = 500) -> str:
        page = await self._get_page()
        try:
            y = amount if direction == "down" else -amount
            await page.mouse.wheel(0, y)
            return f"Scrolled {direction}."
        except Exception as e:
            return f"Scroll error: {e}"

    async def _press(self, key: str) -> str:
        page = await self._get_page()
        try:
            normalized = key.strip()
            normalized = {
                "return": "Enter",
                "enter": "Enter",
                "esc": "Escape",
                "ins": "Insert",
                "del": "Delete",
                "pgup": "PageUp",
                "pgdown": "PageDown",
            }.get(normalized.lower(), key)
            await page.keyboard.press(normalized)
            if normalized != key:
                return f"Pressed: {key} -> {normalized}"
            return f"Pressed: {key}"
        except Exception as e:
            return f"Key error: {e}"

    async def _get_text(self) -> str:
        page = await self._get_page()
        try:
            text = await page.inner_text("body")
            return text[:4000] if len(text) > 4000 else text
        except Exception as e:
            return f"Could not get page text: {e}"

    async def _fill_form(self, fields: dict) -> str:
        page = await self._get_page()
        results = []
        for selector, value in fields.items():
            try:
                el = page.locator(selector).first
                await el.clear()
                await el.type(str(value), delay=40)
                results.append(f"✓ {selector}")
            except Exception as e:
                results.append(f"✗ {selector}: {e}")
        return "Form filled: " + ", ".join(results)

    async def _smart_click(self, description: str) -> str:
        page = await self._get_page()
        desc_lower = description.lower()
        role_hints = {
            "button": ["button", "buton", "btn"],
            "link": ["link", "bağlantı"],
            "searchbox": ["search", "arama"],
            "textbox": ["input", "field", "alan"],
        }
        for role, keywords in role_hints.items():
            if any(k in desc_lower for k in keywords):
                try:
                    await page.get_by_role(role).first.click(timeout=5000)
                    return f"Clicked ({role}): '{description}'"
                except Exception:
                    pass
        try:
            await page.get_by_text(description, exact=False).first.click(timeout=5000)
            return f"Clicked (text): '{description}'"
        except Exception:
            pass
        try:
            await page.get_by_placeholder(description, exact=False).first.click(timeout=5000)
            return f"Clicked (placeholder): '{description}'"
        except Exception:
            pass
        return f"Could not find: '{description}'"

    async def _smart_type(self, description: str, text: str) -> str:
        page = await self._get_page()
        for method, locator in [
            ("placeholder", page.get_by_placeholder(description, exact=False)),
            ("label", page.get_by_label(description, exact=False)),
            ("role", page.get_by_role("textbox")),
        ]:
            try:
                el = locator.first
                await el.clear(timeout=1500)
                await el.type(text, delay=20)
                return f"Typed into ({method}): '{description}'"
            except Exception:
                continue
        return f"Could not find input: '{description}'"

    async def _screenshot(self) -> str:
        page = await self._get_page()
        try:
            img_bytes = await page.screenshot(type="png", full_page=False)
            b64_data = base64.b64encode(img_bytes).decode("utf-8")
            return f"data:image/png;base64,{b64_data}"
        except Exception as e:
            return f"Screenshot error: {e}"

    async def _close_browser(self) -> str:
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
            self._context = None
            self._page = None
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None
        # Hard-stop the event loop to flush Chromium network/dns state.
        # Playwright does not always release the resolver cleanly on its own,
        # which can leave the next launch with net::ERR_NAME_NOT_RESOLVED.
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        return "Browser closed."


_browser = _BrowserThread()
_started = False
_lock = threading.Lock()


def _ensure_started() -> None:
    global _started
    with _lock:
        dead = _browser._thread is not None and not _browser._thread.is_alive()
        closed = _browser._playwright is None and getattr(_browser, "_browser", None) is None
        if not _started or dead or closed:
            _browser.start()
            _started = True


def go_to(url: str, timeout: int = 30) -> str:
    _ensure_started()
    return _browser.run(_browser._go_to(url), timeout=timeout)


def search(query: str, engine: str = "google", timeout: int = 30) -> str:
    _ensure_started()
    return _browser.run(_browser._search(query, engine), timeout=timeout)


def click(selector=None, text=None, timeout: int = 30) -> str:
    _ensure_started()
    return _browser.run(_browser._click(selector=selector, text=text), timeout=timeout)


def type_text(selector=None, text: str = "", clear_first: bool = True, timeout: int = 30) -> str:
    _ensure_started()
    return _browser.run(_browser._type(selector=selector, text=text, clear_first=clear_first), timeout=timeout)


def scroll(direction: str = "down", amount: int = 500, timeout: int = 30) -> str:
    _ensure_started()
    return _browser.run(_browser._scroll(direction=direction, amount=amount), timeout=timeout)


def press(key: str, timeout: int = 30) -> str:
    _ensure_started()
    return _browser.run(_browser._press(key), timeout=timeout)


def get_text(timeout: int = 30) -> str:
    _ensure_started()
    return _browser.run(_browser._get_text(), timeout=timeout)


def fill_form(fields: dict, timeout: int = 60) -> str:
    _ensure_started()
    return _browser.run(_browser._fill_form(fields), timeout=timeout)


def smart_click(description: str, timeout: int = 30) -> str:
    _ensure_started()
    return _browser.run(_browser._smart_click(description), timeout=timeout)


def smart_type(description: str, text: str, timeout: int = 30) -> str:
    _ensure_started()
    return _browser.run(_browser._smart_type(description, text), timeout=timeout)


def screenshot(timeout: int = 30) -> str:
    _ensure_started()
    return _browser.run(_browser._screenshot(), timeout=timeout)


def close_browser(timeout: int = 15) -> str:
    _ensure_started()
    return _browser.run(_browser._close_browser(), timeout=timeout)
