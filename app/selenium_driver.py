"""Selenium implementation of the scraper ``Browser`` (needs Chrome; coverage-omitted).

Ports the login and leaderboard navigation from ``strava_segment_table``: it signs into
Strava with the configured credentials, then drives the segment leaderboard pages so
``app.scraper`` can read each page's HTML and advance the pagination. Modern Selenium
resolves the driver itself (Selenium Manager), so no chromedriver binary is vendored.
"""

from __future__ import annotations

from time import monotonic, sleep
from typing import Any

from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.wait import WebDriverWait

_LOGIN_URL = "https://www.strava.com/login"
_RESULTS = (By.XPATH, "//div[@id='results']/table")
_NEXT_PAGE = (By.XPATH, "//li[@class='next_page']")
_PAGE_SETTLE_SECONDS = 5

# Strava's login is a multi-step flow behind a Cybot cookie banner. Each group lists a
# precise selector first and generic fallbacks after, so it survives Strava revising the
# hashed class names. The steps: accept cookies (they block the form), enter the email
# and continue, decline the one-time-code promo, then enter the password and submit.
_COOKIE_DIALOG = ((By.ID, "CybotCookiebotDialog"),)
_COOKIE_ACCEPT = (
    (By.ID, "CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll"),
    (By.XPATH, "//button[normalize-space()='Accept All']"),
)
# Strava renders both a mobile and a desktop copy of each field (only one shown at a
# time), so these match by shared attributes and ``_find_first`` picks the visible one.
_EMAIL_LOCATORS = (
    (By.CSS_SELECTOR, "input[name='email'][type='email']"),
    (By.CSS_SELECTOR, "[data-cy='email']"),
)
_EMAIL_SUBMIT = (
    (By.CSS_SELECTOR, "[data-cy='login-button']"),
    (By.CSS_SELECTOR, "button[type='submit']"),
)
_USE_PASSWORD = (
    (By.CSS_SELECTOR, "[data-testid='use-password-cta'] button"),
    (By.XPATH, "//button[normalize-space()='Use password instead']"),
)
_PASSWORD_LOCATORS = (
    (By.CSS_SELECTOR, "input[name='password'][type='password']"),
    (By.CSS_SELECTOR, "[data-cy='password']"),
    (By.CSS_SELECTOR, "input[type='password']"),
)
_PASSWORD_SUBMIT = (
    (By.XPATH, "//button[normalize-space()='Log in']"),
    (By.CSS_SELECTOR, "form button[type='submit']"),
)


class SeleniumBrowser:
    """Drives a real Chrome; satisfies ``app.scraper.Browser`` plus login/quit."""

    def __init__(
        self,
        driver: Any = None,
        wait_seconds: int = 10,
        consent_timeout: float = 8.0,
    ) -> None:
        if driver is None:
            options = webdriver.ChromeOptions()
            # A full desktop-width window: a narrow default can trigger a mobile layout
            # that omits the login fields, and it keeps the form and any consent banner
            # on-screen and interactable.
            options.add_argument("--window-size=1920,1080")
            options.add_argument("--start-maximized")
            driver = webdriver.Chrome(options=options)
        self._driver: Any = driver
        self._wait: Any = WebDriverWait(self._driver, wait_seconds)
        self._consent_timeout = consent_timeout

    def login(self, email: str, password: str) -> None:
        """Sign in through Strava's multi-step, cookie-gated login form.

        Accept the cookie banner (the fields are not interactable while it is up), enter
        the email and continue, decline the one-time-code promo in favour of the
        password, then enter the password and submit. Each screen is rendered by
        JavaScript, so every step waits for its control to appear (and to be enabled --
        the submit buttons stay disabled until their field is filled).
        """
        self._driver.get(_LOGIN_URL)
        self._dismiss_consent()
        self._fill(self._wait_interactable(_EMAIL_LOCATORS), email)
        self._click(self._wait_interactable(_EMAIL_SUBMIT, require_enabled=True))
        self._skip_otp_promo()
        self._fill(self._wait_interactable(_PASSWORD_LOCATORS), password)
        self._click(self._wait_interactable(_PASSWORD_SUBMIT, require_enabled=True))

    def _dismiss_consent(self) -> None:
        """Accept the cookie banner and wait for it to disappear before using the form.

        Clicking once is not enough: the banner slides in (so an early click misses) and
        out (so the fields stay covered for a moment), leaving them "not interactable".
        Re-click until the dialog is gone, or give up if it never showed / never leaves.
        """
        deadline = monotonic() + self._consent_timeout
        while self._is_visible(_COOKIE_DIALOG):
            self._click_if_present(_COOKIE_ACCEPT)
            if not self._is_visible(_COOKIE_DIALOG) or monotonic() >= deadline:
                return
            sleep(0.3)

    def _skip_otp_promo(self) -> None:
        """After the email step Strava may promote one-time codes; keep the password."""
        self._wait.until(
            lambda _: (
                self._find_first(_PASSWORD_LOCATORS) is not None
                or self._find_first(_USE_PASSWORD) is not None
            )
        )
        self._click_if_present(_USE_PASSWORD)

    def _wait_interactable(
        self, locators: tuple[tuple[str, str], ...], require_enabled: bool = False
    ) -> Any:
        def ready(_: Any) -> bool:
            element = self._find_first(locators)
            if element is None or not element.is_displayed():
                return False
            return element.is_enabled() if require_enabled else True

        self._wait.until(ready)
        return self._find_first(locators)

    def _is_visible(self, locators: tuple[tuple[str, str], ...]) -> bool:
        element = self._find_first(locators)
        return element is not None and element.is_displayed()

    def _find_first(self, locators: tuple[tuple[str, str], ...]) -> Any:
        """The first *visible* match, falling back to the first present element.

        Strava keeps a hidden mobile copy of each field alongside the shown desktop one;
        returning a present-but-hidden copy would then wait forever to interact with it.
        """
        fallback: Any = None
        for locator in locators:
            for element in self._driver.find_elements(*locator):
                try:
                    visible = element.is_displayed()
                except WebDriverException:
                    visible = False
                if visible:
                    return element
                if fallback is None:
                    fallback = element
        return fallback

    def _scroll_into_view(self, element: Any) -> None:
        self._driver.execute_script("arguments[0].scrollIntoView(true)", element)

    def _fill(self, field: Any, text: str) -> None:
        self._scroll_into_view(field)
        field.clear()
        field.send_keys(text)

    def _click(self, element: Any) -> None:
        self._scroll_into_view(element)
        element.click()

    def _click_if_present(self, locators: tuple[tuple[str, str], ...]) -> None:
        element = self._find_first(locators)
        if element is not None:
            try:
                self._scroll_into_view(element)
                element.click()
            except WebDriverException:
                pass  # best-effort (cookie / OTP promo); ignore if it will not click

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
