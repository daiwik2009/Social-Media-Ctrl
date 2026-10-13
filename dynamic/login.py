# login.py
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout, expect
import json
import os
import time
import tempfile
import webbrowser


# ---------------------------------------------------------------- constants
QR_TIMEOUT_S       = 5 * 60        # how long to give the user to scan / log in
ALREADY_LOGGED_S   = 10            # how long to look for "already logged in" state
GOTO_TIMEOUT_MS    = 60_000
GOTO_RETRIES       = 3
STATUS_PATH        = "credentials/status.json"
DEBUG_DIR          = "debug"

WHATSAPP_URL       = "https://web.whatsapp.com/"
INSTAGRAM_URL      = "https://instagram.com/login"


# ---------------------------------------------------------------- helpers
def save_status(platform: str, status: str, path: str = STATUS_PATH) -> None:
    """Atomically write a valid JSON status file."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    payload = {
        "platform": platform,
        "status": status,
        "timestamp": time.time(),
    }
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def dump_debug(page, prefix: str) -> None:
    """Save a screenshot + HTML snapshot for post-mortem debugging."""
    os.makedirs(DEBUG_DIR, exist_ok=True)
    try:
        page.screenshot(path=f"{DEBUG_DIR}/{prefix}.png", full_page=True)
    except Exception:
        pass
    try:
        with open(f"{DEBUG_DIR}/{prefix}.html", "w", encoding="utf-8") as f:
            f.write(page.content())
    except Exception:
        pass


def goto_with_retry(page, url: str, attempts: int = GOTO_RETRIES) -> None:
    """Navigate, retrying on timeout. Raises if all attempts fail."""
    last_err = None
    for i in range(1, attempts + 1):
        try:
            page.goto(url, wait_until="domcontentloaded",
                      timeout=GOTO_TIMEOUT_MS)
            return
        except PWTimeout as e:
            last_err = e
            print(f"[goto] attempt {i}/{attempts} failed for {url}: {e}")
            page.wait_for_timeout(2000)
    raise RuntimeError(f"Failed to load {url} after {attempts} attempts") from last_err


def wait_for_login(page, platform: str, logged_in_locator, timeout_s: int = QR_TIMEOUT_S) -> None:
    """Block until the 'logged in' indicator becomes visible, else raise."""
    try:
        expect(logged_in_locator).to_be_visible(timeout=timeout_s * 1000)
    except PWTimeout:
        dump_debug(page, f"{platform}_timeout")
        raise RuntimeError(
            f"{platform}: login did not complete within {timeout_s}s "
            f"(see {DEBUG_DIR}/{platform}_timeout.png)"
        )
    save_status(platform, "logged")
    print(f"[{platform}] Login successful.")


def is_logged_in_now(page, locator) -> bool:
    """Non-blocking check — safe to call in a race loop."""
    try:
        return locator.is_visible()
    except Exception:
        return False


# or whatsapp
def _login_whatsapp(p) -> None:
    browser = p.chromium.launch(headless=True)
    try:
        page = browser.new_page()

        goto_with_retry(page, WHATSAPP_URL)

        
        qr_locator     = page.locator(
            'canvas[aria-label*="Scan"], '
            'div[data-ref], '
            'img[src*="qr"]'
        ).first

        logged_locator = page.locator(
            '#pane-side, '
            'div[aria-label="Chat list"], '
            'div[data-testid="chat-list"]'
        ).first

        # Race: are we already logged in from a persistent session?
        start = time.time()
        while time.time() - start < ALREADY_LOGGED_S:
            if is_logged_in_now(page, logged_locator):
                save_status("Whatsapp", "logged")
                print("[Whatsapp] Already logged in.")
                return
            if is_logged_in_now(page, qr_locator):
                break
            page.wait_for_timeout(500)
        else:

            print("[Whatsapp] Could not detect QR or chat list yet; continuing.")

    
        if is_logged_in_now(page, qr_locator):
            qr_path = "qr-code.png"
            try:
                qr_locator.screenshot(path=qr_path)
                print(f"[Whatsapp] QR saved to {qr_path}")
                webbrowser.open(qr_path)
            except Exception as e:
                print(f"[Whatsapp] Could not save/open QR: {e}")

        wait_for_login(page, "Whatsapp", logged_locator, QR_TIMEOUT_S)

        
        try:
            os.remove("qr-code.png")
        except FileNotFoundError:
            pass
        except OSError as e:
            print(f"[Whatsapp] Could not remove qr-code.png: {e}")

    finally:
        browser.close()


# for instagram
def _login_instagram(p) -> None:
    browser = p.chromium.launch(headless=False)
    try:
        page = browser.new_page()

        goto_with_retry(page, INSTAGRAM_URL)

        logged_locator = page.locator(
            'svg[aria-label="Home"], '
            'a[href="/direct/inbox/"], '
            'div[role="navigation"]'
        ).first

        wait_for_login(page, "Instagram", logged_locator, QR_TIMEOUT_S)

    finally:
        browser.close()


# pipersssss
def login(platform: str) -> None:
    """
    Entry point. `platform` is one of: 'wtp', 'inst'.
    Keeps the original call shape so external pipers don't need to change.
    """
    platform = platform.lower().strip()

    with sync_playwright() as p:
        if platform == "wtp":
            _login_whatsapp(p)
        elif platform == "inst":
            _login_instagram(p)
        else:
            raise ValueError(f"Unknown platform: {platform!r} (expected 'wtp' or 'inst')")

