"""Tests for the Selenium login flow, driven by a fake WebDriver (no real browser).

``selenium_driver`` is coverage-omitted (it normally needs Chrome), but Strava's
multi-step, cookie-gated login is fiddly enough to be worth guarding, so a fake driver
records the calls the flow makes at each step.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By

from app.selenium_driver import SeleniumBrowser

_DIALOG = (By.ID, "CybotCookiebotDialog")
_ACCEPT = (By.ID, "CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll")
_EMAIL = (By.CSS_SELECTOR, "input[name='email'][type='email']")
_EMAIL_SUBMIT = (By.CSS_SELECTOR, "[data-cy='login-button']")
_USE_PASSWORD = (By.CSS_SELECTOR, "[data-testid='use-password-cta'] button")
_PASSWORD = (By.CSS_SELECTOR, "input[name='password'][type='password']")
_PASSWORD_SUBMIT = (By.XPATH, "//button[normalize-space()='Log in']")


class _FakeElement:
    def __init__(
        self, displayed: bool = True, on_click: Callable[[], None] | None = None
    ) -> None:
        self.cleared = False
        self.sent: str | None = None
        self.clicked = False
        self.displayed = displayed
        self._on_click = on_click

    def clear(self) -> None:
        self.cleared = True

    def send_keys(self, text: str) -> None:
        self.sent = text

    def click(self) -> None:
        self.clicked = True
        if self._on_click is not None:
            self._on_click()

    def is_enabled(self) -> bool:
        return True

    def is_displayed(self) -> bool:
        return self.displayed


class _FakeDriver:
    def __init__(self, elements: dict[tuple[Any, str], list[_FakeElement]]) -> None:
        self._elements = elements
        self.visited: list[str] = []
        self.page_source = "<html>FAKE PAGE</html>"

    def get(self, url: str) -> None:
        self.visited.append(url)

    def find_elements(self, by: Any, selector: str) -> list[_FakeElement]:
        return self._elements.get((by, selector), [])

    def execute_script(self, script: str, *args: Any) -> None:
        return None

    def save_screenshot(self, path: str) -> bool:
        Path(path).write_bytes(b"PNG")
        return True


def test_login_walks_the_multi_step_form_and_dismisses_the_banner() -> None:
    dialog = _FakeElement()
    accept = _FakeElement(on_click=lambda: setattr(dialog, "displayed", False))
    # Strava ships a hidden mobile copy of the email field beside the visible desktop
    # one; the flow must fill the visible copy, not the hidden first match.
    hidden_email = _FakeElement(displayed=False)
    email, esub, usepw = _FakeElement(), _FakeElement(), _FakeElement()
    pw, psub = _FakeElement(), _FakeElement()
    driver = _FakeDriver(
        {
            _DIALOG: [dialog],
            _ACCEPT: [accept],
            _EMAIL: [hidden_email, email],
            _EMAIL_SUBMIT: [esub],
            _USE_PASSWORD: [usepw],
            _PASSWORD: [pw],
            _PASSWORD_SUBMIT: [psub],
        }
    )
    browser = SeleniumBrowser(driver=driver, wait_seconds=1)
    browser.login("me@example.com", "secret")
    assert accept.clicked  # cookie banner accepted...
    assert dialog.displayed is False  # ...and gone before the form is touched
    assert hidden_email.sent is None  # the hidden mobile copy is skipped
    assert email.sent == "me@example.com"  # the visible copy is filled
    assert esub.clicked
    assert usepw.clicked  # one-time-code promo declined for the password
    assert pw.sent == "secret"
    assert psub.clicked


def test_login_skips_promo_when_password_shown_directly() -> None:
    usepw = _FakeElement()
    pw, psub = _FakeElement(), _FakeElement()
    driver = _FakeDriver(
        {
            # no dialog and no use-password: no banner, straight to the password screen
            _EMAIL: [_FakeElement()],
            _EMAIL_SUBMIT: [_FakeElement()],
            _PASSWORD: [pw],
            _PASSWORD_SUBMIT: [psub],
        }
    )
    browser = SeleniumBrowser(driver=driver, wait_seconds=1)
    browser.login("a@b.c", "pw123")
    assert not usepw.clicked
    assert pw.sent == "pw123"
    assert psub.clicked


def test_login_failure_saves_page_source_and_screenshot(tmp_path) -> None:
    driver = _FakeDriver({})  # nothing to find -> the email step times out
    browser = SeleniumBrowser(
        driver=driver, wait_seconds=1, diagnostics_dir=str(tmp_path)
    )
    with pytest.raises(WebDriverException):
        browser.login("a@b.c", "pw")
    htmls = list(tmp_path.glob("login_failure_*.html"))
    pngs = list(tmp_path.glob("login_failure_*.png"))
    assert htmls and pngs
    assert "FAKE PAGE" in htmls[0].read_text(encoding="utf-8")


class _LoginPollDriver:
    """Fake driver whose cookies gain a 'remember' cookie after a few polls."""

    def __init__(self, appears_after: int) -> None:
        self._appears_after = appears_after
        self._polls = 0

    def get(self, url: str) -> None:
        pass

    def find_elements(self, by: Any, selector: str) -> list[_FakeElement]:
        return []  # no cookie dialog to dismiss

    def get_cookies(self) -> list[dict[str, str]]:
        self._polls += 1
        if self._polls >= self._appears_after:
            return [{"name": "strava_remember_token", "value": "tok"}]
        return [{"name": "_strava4_session", "value": "sess"}]


def test_wait_for_manual_login_returns_cookies_once_signed_in() -> None:
    browser = SeleniumBrowser(driver=_LoginPollDriver(appears_after=3))
    cookies = browser.wait_for_manual_login(timeout=5, poll=0.01)
    assert {c["name"] for c in cookies} == {"strava_remember_token"}


def test_wait_for_manual_login_times_out_without_a_session() -> None:
    browser = SeleniumBrowser(driver=_LoginPollDriver(appears_after=9999))
    with pytest.raises(TimeoutError):
        browser.wait_for_manual_login(timeout=0.05, poll=0.01)
