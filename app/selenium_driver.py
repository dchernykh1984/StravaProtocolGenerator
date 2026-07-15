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
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.wait import WebDriverWait

_LOGIN_URL = "https://www.strava.com/login"
_RESULTS = (By.XPATH, "//div[@id='results']/table")
_NEXT_PAGE = (By.XPATH, "//li[@class='next_page']")
_PAGE_SETTLE_SECONDS = 5


class SeleniumBrowser:
    """Drives a real Chrome; satisfies ``app.scraper.Browser`` plus login/quit."""

    def __init__(self, driver: Any = None, wait_seconds: int = 10) -> None:
        self._driver: Any = driver if driver is not None else webdriver.Chrome()
        self._wait: Any = WebDriverWait(self._driver, wait_seconds)

    def login(self, email: str, password: str) -> None:
        self._driver.get(_LOGIN_URL)
        self._driver.find_element(By.ID, "email").send_keys(email)
        self._driver.find_element(By.ID, "password").send_keys(password)
        self._driver.find_element(By.XPATH, "//button[@type='submit']").click()

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
