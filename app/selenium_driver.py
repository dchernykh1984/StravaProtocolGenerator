"""Selenium implementation of the scraper ``Browser`` (needs Chrome; coverage-omitted).

Ports the login and leaderboard navigation from ``strava_segment_table``: it signs into
Strava with the configured credentials, then drives the segment leaderboard pages so
``app.scraper`` can read each page's HTML and advance the pagination. Modern Selenium
resolves the driver itself (Selenium Manager), so no chromedriver binary is vendored.
"""

from __future__ import annotations

from time import sleep
from typing import Any

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.wait import WebDriverWait

_LOGIN_URL = "https://www.strava.com/login"
_RESULTS = (By.XPATH, "//div[@id='results']/table")
_NEXT_PAGE = (By.XPATH, "//li[@class='next_page']")
_PAGE_SETTLE_SECONDS = 5

# Strava renders the login form with JavaScript and revises its markup over time, so we
# wait for the field to appear and try several locators (the ``type=`` ones survive id
# and name changes) rather than depending on a single fixed id.
_EMAIL_LOCATORS = (
    (By.ID, "email"),
    (By.NAME, "email"),
    (By.CSS_SELECTOR, "input[type='email']"),
)
_PASSWORD_LOCATORS = (
    (By.ID, "password"),
    (By.NAME, "password"),
    (By.CSS_SELECTOR, "input[type='password']"),
)
_SUBMIT_LOCATORS = (
    (By.CSS_SELECTOR, "button[type='submit']"),
    (By.ID, "login-button"),
    (By.XPATH, "//button[contains(., 'Log In') or contains(., 'Login')]"),
)
_CONSENT_LOCATORS = (
    (By.ID, "onetrust-accept-btn-handler"),
    (By.CSS_SELECTOR, "button[aria-label='Accept']"),
)


class SeleniumBrowser:
    """Drives a real Chrome; satisfies ``app.scraper.Browser`` plus login/quit."""

    def __init__(self, driver: Any = None, wait_seconds: int = 10) -> None:
        self._driver: Any = driver if driver is not None else webdriver.Chrome()
        self._wait: Any = WebDriverWait(self._driver, wait_seconds)

    def login(self, email: str, password: str) -> None:
        """Sign in, waiting for the form and tolerating login-page markup changes."""
        self._driver.get(_LOGIN_URL)
        self._click_if_present(_CONSENT_LOCATORS)
        self._wait.until(lambda _: self._find_first(_EMAIL_LOCATORS) is not None)
        self._type_into(_EMAIL_LOCATORS, email)
        self._type_into(_PASSWORD_LOCATORS, password)
        submit = self._find_first(_SUBMIT_LOCATORS)
        if submit is None:
            raise NoSuchElementException("Strava login submit button not found")
        submit.click()

    def _find_first(self, locators: tuple[tuple[str, str], ...]) -> Any:
        for locator in locators:
            elements = self._driver.find_elements(*locator)
            if elements:
                return elements[0]
        return None

    def _type_into(self, locators: tuple[tuple[str, str], ...], text: str) -> None:
        field = self._find_first(locators)
        if field is None:
            raise NoSuchElementException(f"Strava login field not found: {locators}")
        field.clear()
        field.send_keys(text)

    def _click_if_present(self, locators: tuple[tuple[str, str], ...]) -> None:
        element = self._find_first(locators)
        if element is not None:
            try:
                element.click()
            except WebDriverException:
                pass  # a consent banner is best-effort; ignore if it will not dismiss

    def cookies(self) -> list[dict[str, Any]]:
        """Return the current session cookies (call after a successful login).

        Visits the dashboard first so Strava has issued the signed-in session cookie,
        then hands back the whole jar for the HTTP scraper to reuse without re-login.
        """
        self._driver.get("https://www.strava.com/dashboard")
        sleep(_PAGE_SETTLE_SECONDS)
        return list(self._driver.get_cookies())

    def get(self, url: str) -> None:
        self._driver.get(url)
        self._wait.until(ec.presence_of_element_located(_RESULTS))

    def page_source(self) -> str:
        return str(self._driver.page_source)

    def has_next_page(self) -> bool:
        buttons = self._driver.find_elements(*_NEXT_PAGE)
        if not buttons:
            return False
        css = buttons[0].get_attribute("class") or ""
        return not css.startswith("disabled")

    def go_next_page(self) -> None:
        link = self._driver.find_element(*_NEXT_PAGE).find_element(By.TAG_NAME, "a")
        link.click()
        sleep(_PAGE_SETTLE_SECONDS)
        self._wait.until(ec.presence_of_element_located(_RESULTS))

    def quit(self) -> None:
        self._driver.quit()
