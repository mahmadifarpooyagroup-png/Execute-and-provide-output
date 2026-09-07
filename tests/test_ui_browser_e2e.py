from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request

import pytest
from playwright.sync_api import Page, sync_playwright


RUNTIME_URL = "http://127.0.0.1:8765"
FRONTEND_URL = "http://127.0.0.1:5173"
E2E_TOKEN = "atrin-ui-e2e-token-8e5de6d1d1c54284a6d7f1f7"


def wait_for_http(url: str, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status < 500:
                    return
        except Exception as error:
            last_error = error
        time.sleep(0.5)
    raise RuntimeError(f"Timed out waiting for {url}: {last_error}")


@pytest.fixture(scope="module")
def browser_servers(tmp_path_factory):
    root = tmp_path_factory.mktemp("ui-e2e")
    env = os.environ.copy()
    env.update({
        "PYTHONPATH": os.getcwd(),
        "ATRIN_E2E_TOKEN": E2E_TOKEN,
        "ATRIN_DB_PATH": str(root / "runtime.db"),
        "ATRIN_RUNTIME_TOKEN_PATH": str(root / "runtime.token"),
        "ATRIN_UI_E2E_PORT": "8765",
        "VITE_ATRIN_API_URL": RUNTIME_URL,
    })
    runtime = subprocess.Popen(
        [sys.executable, "tests/ui_e2e_server.py"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    frontend = subprocess.Popen(
        ["npm", "run", "dev", "--", "--host", "127.0.0.1", "--port", "5173"],
        cwd="frontend",
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        wait_for_http(f"{RUNTIME_URL}/health")
        wait_for_http(FRONTEND_URL)
        yield frontend, runtime
    finally:
        for process in (frontend, runtime):
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def seed_session(page: Page) -> None:
    page.add_init_script(
        "window.sessionStorage.setItem('atrin.runtime.token', %r);"
        "window.localStorage.setItem('i18nextLng', 'en');" % E2E_TOKEN
    )


def test_provider_and_workflow_journey(browser_servers):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        seed_session(page)
        page.goto(FRONTEND_URL, wait_until="networkidle")

        page.get_by_role("link", name="Providers").click()
        page.get_by_label("Profile ID").fill("ui-e2e-profile")
        page.get_by_label("Account ID").fill("ui-e2e-account")
        page.get_by_label("Display name").fill("UI E2E Profile")
        page.get_by_role("button", name="Add provider").click()
        page.get_by_text("UI E2E Profile").wait_for()

        page.get_by_role("link", name="Workflows").click()
        page.get_by_label("Workflow goal").fill("Validate Atrin desktop workflow")
        page.get_by_label("First action").fill("hello from browser")
        page.get_by_role("button", name="Create workflow").click()
        page.get_by_text("Validate Atrin desktop workflow").wait_for()

        page.get_by_role("button", name="Run next").click()
        page.get_by_text("100% complete").wait_for(timeout=10000)
        page.get_by_text("completed").wait_for()

        page.get_by_role("link", name="Dashboard").click()
        page.get_by_text("1", exact=True).first.wait_for()
        browser.close()
