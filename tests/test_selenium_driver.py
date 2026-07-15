"""Tests for the Selenium login flow, driven by a fake WebDriver (no real browser).

``selenium_driver`` is coverage-omitted (it normally needs Chrome), but the login logic
-- accept the cookie banner, then fill and submit -- is worth guarding, so a fake driver
records the calls the flow makes.
"""

from __future__ import annotations

from typing import Any

from selenium.webdriver.common.by import By

from app.selenium_driver import SeleniumBrowser


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


class _FakeDriver:
    def __init__(self, elements: dict[tuple[Any, str], list[_FakeElement]]) -> None:
        self._elements = elements
        self.visited: list[str] = []
        self.scrolled: list[_FakeElement] = []

    def get(self, url: str) -> None:
        self.visited.append(url)

    def find_elements(self, by: Any, selector: str) -> list[_FakeElement]:
        return self._elements.get((by, selector), [])

    def execute_script(self, script: str, *args: Any) -> None:
        self.scrolled.append(args[0])


def test_login_accepts_cookies_then_fills_and_submits() -> None:
    accept, email, password, submit = (_FakeElement() for _ in range(4))
    driver = _FakeDriver(
        {
            (By.XPATH, "//button[normalize-space()='Accept All']"): [accept],
            (By.ID, "email"): [email],
            (By.ID, "password"): [password],
            (By.CSS_SELECTOR, "button[type='submit']"): [submit],
        }
    )
    browser = SeleniumBrowser(driver=driver, wait_seconds=1)
    browser.login("me@example.com", "secret")
    assert driver.visited == ["https://www.strava.com/login"]
    assert accept.clicked  # cookie banner dismissed before touching the form
    assert email.sent == "me@example.com"
    assert password.sent == "secret"
    assert submit.clicked


def test_login_without_a_banner_uses_fallback_locators() -> None:
    email, password, submit = (_FakeElement() for _ in range(3))
    driver = _FakeDriver(
        {
            (By.CSS_SELECTOR, "input[type='email']"): [email],
            (By.CSS_SELECTOR, "input[type='password']"): [password],
            (By.ID, "login-button"): [submit],
        }
    )
    browser = SeleniumBrowser(driver=driver, wait_seconds=1, consent_timeout=0.1)
    browser.login("a@b.c", "pw")
    assert email.sent == "a@b.c"
    assert password.sent == "pw"
    assert submit.clicked
