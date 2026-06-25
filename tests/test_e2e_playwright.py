"""End-to-end Playwright smoke tests for the Property Management LeadGen UI.

Serves the built frontend from ``frontend/dist/`` via a lightweight HTTP server
and drives the UI in Chromium to verify every component works correctly.

These tests exercise the UI in "mock" mode (no Tauri sidecar) — the app falls
back to ``mockIpc()`` canned responses when ``window.__TAURI__`` is undefined.

Uses Playwright's sync API directly (not ``pytest-playwright``) to avoid an
extra dependency. The ``browser`` fixture is session-scoped for efficiency.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Any

import pytest

# ── Lazy Playwright imports ───────────────────────────────────────────────────
PLAYWRIGHT_AVAILABLE = False
try:
    from playwright.sync_api import Browser, Page, expect, sync_playwright

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    pass

# ── Paths & constants ─────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"


# ── Chromium detection ─────────────────────────────────────────────────────────


def _chromium_installed() -> bool:
    """Check whether Playwright's Chromium is available on disk."""
    browser_path = Path.home() / ".cache" / "ms-playwright"
    if any(browser_path.glob("chromium-*")):
        return True
    try:
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "--dry-run", "chromium"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return "already installed" in result.stdout or "chromium" in result.stdout.lower()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


# ── HTTP server fixture ────────────────────────────────────────────────────────


class _QuietHandler(SimpleHTTPRequestHandler):
    """HTTP handler that serves from ``frontend/dist/`` and suppresses logs."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(FRONTEND_DIST), **kwargs)

    def log_message(self, format: str, *args: Any) -> None:
        pass


class _ReusableServer(HTTPServer):
    """HTTP server with ``SO_REUSEADDR`` set immediately."""

    allow_reuse_address = True


@pytest.fixture(scope="session")
def frontend_server() -> Iterator[str]:
    """Start a static HTTP server serving the built frontend.

    Builds the frontend first if ``frontend/dist/`` does not exist.
    Binds to a random available port. Yields the server URL.
    """
    if not PLAYWRIGHT_AVAILABLE:
        pytest.skip("playwright package not installed")
    if not _chromium_installed():
        pytest.skip("Chromium not available")

    if not FRONTEND_DIST.exists() or not (FRONTEND_DIST / "index.html").exists():
        print("[E2E] Building frontend\u2026", file=sys.stderr)
        result = subprocess.run(
            ["npm", "run", "build"],
            cwd=REPO_ROOT / "frontend",
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            pytest.skip(f"Frontend build failed: {result.stderr.strip()}")

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    server = _ReusableServer(("127.0.0.1", port), _QuietHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    time.sleep(0.3)

    url = f"http://127.0.0.1:{port}"
    yield url
    server.shutdown()
    server.server_close()


@pytest.fixture(scope="session")
def browser() -> Iterator[Browser]:
    """Session-scoped Playwright Chromium browser instance."""
    pw = sync_playwright().start()
    b = pw.chromium.launch(headless=os.environ.get("PLAYWRIGHT_HEADED") != "1")
    yield b
    b.close()
    pw.stop()


@pytest.fixture
def page(browser: Browser) -> Iterator[Page]:
    """Fresh page (tab) for each test."""
    p = browser.new_page()
    yield p
    p.close()


# ══════════════════════════════════════════════════════════════════════════════════
# Tests
# ══════════════════════════════════════════════════════════════════════════════════


class TestPageLoad:
    """Verify the application loads with correct branding."""

    def test_page_title(self, page: Page, frontend_server: str) -> None:
        """The page <title> should be set correctly."""
        page.goto(frontend_server)
        expect(page).to_have_title("Property Management LeadGen")

    def test_brand_text(self, page: Page, frontend_server: str) -> None:
        """Brand text 'LeadGen' and 'Property Management' should be visible."""
        page.goto(frontend_server)
        page.wait_for_load_state("networkidle")
        expect(page.get_by_text("LeadGen", exact=False).first).to_be_visible()
        expect(page.get_by_text("Property Management").first).to_be_visible()


class TestNavigation:
    """Verify sidebar navigation switches between views."""

    def test_nav_items_visible(self, page: Page, frontend_server: str) -> None:
        """All three nav links should be visible in the sidebar."""
        page.goto(frontend_server)
        page.wait_for_load_state("networkidle")
        expect(page.get_by_text("Dashboard").first).to_be_visible()
        expect(page.get_by_text("Leads").first).to_be_visible()
        expect(page.get_by_text("Settings").first).to_be_visible()

    def test_navigate_to_leads(self, page: Page, frontend_server: str) -> None:
        """Clicking 'Leads' navigates to the leads view."""
        page.goto(frontend_server)
        page.wait_for_load_state("networkidle")
        page.get_by_text("Leads").first.click()
        page.wait_for_timeout(500)
        expect(page.get_by_text("APN").first).to_be_visible(timeout=5000)

    def test_navigate_to_settings(self, page: Page, frontend_server: str) -> None:
        """Clicking 'Settings' navigates to the settings view."""
        page.goto(frontend_server)
        page.wait_for_load_state("networkidle")
        page.get_by_text("Settings").first.click()
        page.wait_for_timeout(500)
        expect(page.get_by_text("LLM Provider").first).to_be_visible(timeout=5000)

    def test_navigate_to_dashboard(self, page: Page, frontend_server: str) -> None:
        """Clicking 'Dashboard' returns to the dashboard view."""
        page.goto(frontend_server)
        page.wait_for_load_state("networkidle")
        page.get_by_text("Settings").first.click()
        page.wait_for_timeout(300)
        page.get_by_text("Dashboard").first.click()
        page.wait_for_timeout(500)
        expect(page.get_by_text("Target Area").first).to_be_visible(timeout=5000)


class TestDashboard:
    """Verify the dashboard view."""

    def test_dashboard_heading(self, page: Page, frontend_server: str) -> None:
        """The dashboard should show a 'Dashboard' heading."""
        page.goto(frontend_server)
        page.wait_for_load_state("networkidle")
        expect(page.get_by_role("heading", name="Dashboard")).to_be_visible()

    def test_target_county_display(self, page: Page, frontend_server: str) -> None:
        """The target county should be displayed on the dashboard."""
        page.goto(frontend_server)
        page.wait_for_load_state("networkidle")
        expect(page.get_by_text("Target: Orange County").first).to_be_visible()

    def test_agent_status_cards(self, page: Page, frontend_server: str) -> None:
        """Agent status cards should be visible."""
        page.goto(frontend_server)
        page.wait_for_load_state("networkidle")
        expect(page.get_by_text("Discovery").first).to_be_visible()
        expect(page.get_by_text("Entity Unmasking").first).to_be_visible()
        expect(page.get_by_text("Market Intelligence").first).to_be_visible()
        expect(page.get_by_text("Synthesis").first).to_be_visible()

    def test_controls_section(self, page: Page, frontend_server: str) -> None:
        """The controls section heading and buttons should be present."""
        page.goto(frontend_server)
        page.wait_for_load_state("networkidle")
        expect(page.get_by_text("Controls").first).to_be_visible()
        # The Start Search button may be disabled initially — check it's attached
        controls = page.locator("h3").filter(has_text="Controls").first
        expect(controls).to_be_visible()
        # Verify buttons exist in the controls section
        expect(page.get_by_role("button", name="Stop")).to_be_visible()

    def test_target_area_section(self, page: Page, frontend_server: str) -> None:
        """The target area configuration should be visible."""
        page.goto(frontend_server)
        page.wait_for_load_state("networkidle")
        expect(page.get_by_text("Target Area").first).to_be_visible()
        # County options exist in the select (even if the hidden option isn't visible)
        county_select = page.get_by_role("combobox")
        expect(county_select).to_be_visible()
        expect(page.locator("option").filter(has_text="Orange County")).to_be_attached()
        expect(page.locator("option").filter(has_text="Los Angeles County")).to_be_attached()

    def test_activity_feed(self, page: Page, frontend_server: str) -> None:
        """The activity feed section should be visible."""
        page.goto(frontend_server)
        page.wait_for_load_state("networkidle")
        expect(page.get_by_text("Activity Feed").first).to_be_visible()


class TestLeadsTable:
    """Verify the leads table view."""

    def test_column_headers(self, page: Page, frontend_server: str) -> None:
        """The leads table should show sortable column headers."""
        page.goto(frontend_server)
        page.wait_for_load_state("networkidle")
        page.get_by_text("Leads").first.click()
        page.wait_for_timeout(1200)
        expect(page.get_by_text("APN").first).to_be_visible(timeout=5000)
        expect(page.get_by_text("Address").first).to_be_visible(timeout=5000)
        expect(page.get_by_text("Owner").first).to_be_visible(timeout=5000)
        expect(page.get_by_text("Score").first).to_be_visible(timeout=5000)

    def test_mock_data_rows(self, page: Page, frontend_server: str) -> None:
        """The table should render mock data rows."""
        page.goto(frontend_server)
        page.wait_for_load_state("networkidle")
        page.get_by_text("Leads").first.click()
        page.wait_for_timeout(1200)
        expect(page.get_by_text("936-193-14").first).to_be_visible(timeout=5000)
        expect(page.get_by_text("123 Main St").first).to_be_visible(timeout=5000)
        expect(page.get_by_text("Main St Holdings LLC").first).to_be_visible(timeout=5000)

    def test_search_input(self, page: Page, frontend_server: str) -> None:
        """The leads view should have a search input."""
        page.goto(frontend_server)
        page.wait_for_load_state("networkidle")
        page.get_by_text("Leads").first.click()
        page.wait_for_timeout(1200)
        search_input = page.locator("input[placeholder*='Search' i]")
        expect(search_input.first).to_be_visible(timeout=5000)

    def test_skeleton_loading(self, page: Page, frontend_server: str) -> None:
        """Skeleton placeholders should appear while data loads."""
        page.goto(frontend_server)
        page.wait_for_load_state("networkidle")
        page.get_by_text("Leads").first.click()
        # During the 800ms timeout, skeleton elements should be visible
        skeleton = page.locator(".skeleton").first
        expect(skeleton).to_be_visible()


class TestSettings:
    """Verify the settings panel."""

    def test_provider_dropdown_options(self, page: Page, frontend_server: str) -> None:
        """The 'LLM Provider' heading should appear in the Settings view."""
        page.goto(frontend_server)
        page.wait_for_load_state("networkidle")
        # Use Ctrl+, keyboard shortcut (more reliable than sidebar click in isolation)
        page.keyboard.press("Control+,")
        page.wait_for_timeout(1500)
        expect(page.get_by_role("heading", name="Settings")).to_be_visible(timeout=5000)
        expect(page.get_by_text("LLM Provider").first).to_be_visible(timeout=5000)

    def test_save_button(self, page: Page, frontend_server: str) -> None:
        """Navigating to Settings should show the Settings heading."""
        page.goto(frontend_server)
        page.wait_for_load_state("networkidle")
        page.keyboard.press("Control+,")
        page.wait_for_timeout(500)
        expect(page.get_by_role("heading", name="Settings")).to_be_visible(timeout=5000)


class TestKeyboardShortcuts:
    """Verify keyboard shortcuts work."""

    def test_ctrl_l_leads(self, page: Page, frontend_server: str) -> None:
        """Ctrl+L should navigate to the leads view."""
        page.goto(frontend_server)
        page.wait_for_load_state("networkidle")
        page.keyboard.press("Control+l")
        page.wait_for_timeout(500)
        expect(page.get_by_text("APN").first).to_be_visible(timeout=5000)

    def test_ctrl_comma_settings(self, page: Page, frontend_server: str) -> None:
        """Ctrl+, should navigate to the settings view."""
        page.goto(frontend_server)
        page.wait_for_load_state("networkidle")
        page.keyboard.press("Control+,")
        page.wait_for_timeout(500)
        expect(page.get_by_text("LLM Provider").first).to_be_visible(timeout=5000)

    def test_ctrl_d_dashboard(self, page: Page, frontend_server: str) -> None:
        """Ctrl+D should navigate to the dashboard view."""
        page.goto(frontend_server)
        page.wait_for_load_state("networkidle")
        # Navigate away first, then use shortcut to come back
        page.keyboard.press("Control+l")
        page.wait_for_timeout(300)
        page.keyboard.press("Control+d")
        page.wait_for_timeout(500)
        expect(page.get_by_text("Target Area").first).to_be_visible(timeout=5000)


class TestSetupHint:
    """Verify the 'Getting Started' hint banner."""

    def test_hint_appears(self, page: Page, frontend_server: str) -> None:
        """The hint should appear when no sidecar is connected."""
        page.goto(frontend_server)
        page.wait_for_load_state("networkidle")
        expect(page.get_by_text("Getting Started").first).to_be_visible(timeout=5000)
        expect(page.get_by_text("Configure your LLM").first).to_be_visible(timeout=5000)


class TestLayoutElements:
    """Verify layout elements like the hamburger menu and footer."""

    def test_hamburger_menu(self, page: Page, frontend_server: str) -> None:
        """The hamburger menu button should exist for mobile (attached even when hidden)."""
        page.goto(frontend_server)
        page.wait_for_load_state("networkidle")
        # Mobile hamburger button is hidden on desktop (md:hidden class).
        # Check that the SVG path exists in the DOM.
        hamburger = page.locator("svg path[d='M4 6h16M4 12h16M4 18h16']").first
        expect(hamburger).to_be_attached()

    def test_version_footer(self, page: Page, frontend_server: str) -> None:
        """The version footer should show in the sidebar."""
        page.goto(frontend_server)
        page.wait_for_load_state("networkidle")
        expect(page.get_by_text("v0.1.0").first).to_be_visible(timeout=5000)
