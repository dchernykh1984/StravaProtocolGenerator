"""Tests for the Selenium login flow, driven by a fake WebDriver (no real browser).

``selenium_driver`` is coverage-omitted (it normally needs Chrome), but Strava's
multi-step, cookie-gated login is fiddly enough to be worth guarding, so a fake driver
records the calls the flow makes at each step.
"""

from __future__ import annotations

from typing import Any

from selenium.webdriver.common.by import By

from app.selenium_driver import SeleniumBrowser

_COOKIE = (By.ID, "CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll")
_EMAIL = (By.ID, "mobile-email")
_EMAIL_SUBMIT = (By.ID, "mobile-login-button")
_USE_PASSWORD = (By.CSS_SELECTOR, "[data-testid='use-password-cta'] button")
_PASSWORD = (By.CSS_SELECTOR, "input[name='password'][type='password']")
_PASSWORD_SUBMIT = (By.XPATH, "//button[normalize-space()='Log in']")


class _FakeElement:
    def __init__(self) -> None:
        self.cleared = False
        self.sent: str | None = None
        self.clicked = False

    def clear(self) -> None:
        self.cleared = True

    def send_keys(self, text: str) -> None:
        self.sent = text

    def click(self) -> None:
        self.clicked = True

    def is_enabled(self) -> bool:
        return True


class _FakeDriver:
    def __init__(self, elements: dict[tuple[Any, str], list[_FakeElement]]) -> None:
        self._elements = elements
        self.visited: list[str] = []

    def get(self, url: str) -> None:
        self.visited.append(url)

    def find_elements(self, by: Any, selector: str) -> list[_FakeElement]:
        return self._elements.get((by, selector), [])

    def execute_script(self, script: str, *args: Any) -> None:
        return None


def test_login_walks_the_multi_step_form() -> None:
    names = ("cookie", "email", "esub", "usepw", "pw", "psub")
    parts = {name: _FakeElement() for name in names}
    driver = _FakeDriver(
        {
            _COOKIE: [parts["cookie"]],
            _EMAIL: [parts["email"]],
            _EMAIL_SUBMIT: [parts["esub"]],
            _USE_PASSWORD: [parts["usepw"]],
            _PASSWORD: [parts["pw"]],
            _PASSWORD_SUBMIT: [parts["psub"]],
        }
    )
    browser = SeleniumBrowser(driver=driver, wait_seconds=1)
    browser.login("me@example.com", "secret")
    assert driver.visited == ["https://www.strava.com/login"]
    assert parts["cookie"].clicked  # Cybot cookie banner accepted
    assert parts["email"].sent == "me@example.com"
    assert parts["esub"].clicked
    assert parts["usepw"].clicked  # one-time-code promo declined for the password
    assert parts["pw"].sent == "secret"
    assert parts["psub"].clicked


def test_login_skips_promo_when_password_shown_directly() -> None:
    usepw = _FakeElement()
    pw, psub = _FakeElement(), _FakeElement()
    driver = _FakeDriver(
        {
            _COOKIE: [_FakeElement()],
            _EMAIL: [_FakeElement()],
            _EMAIL_SUBMIT: [_FakeElement()],
            # no _USE_PASSWORD entry: Strava went straight to the password screen
            _PASSWORD: [pw],
            _PASSWORD_SUBMIT: [psub],
        }
    )
    browser = SeleniumBrowser(driver=driver, wait_seconds=1)
    browser.login("a@b.c", "pw123")
    assert not usepw.clicked
    assert pw.sent == "pw123"
    assert psub.clicked
