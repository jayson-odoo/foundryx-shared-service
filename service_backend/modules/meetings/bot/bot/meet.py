"""Google Meet driver: login, join, consent, participant / speaker polling, leave detection."""
from __future__ import annotations

import time
from dataclasses import dataclass

from playwright.sync_api import Page, TimeoutError as PWTimeout

from . import meet_selectors as S
from .events import Events


class BotError(RuntimeError):
    """Raised with a one-line reason; the caller screenshots and exits 1 (AC-S1-9)."""


@dataclass
class Poll:
    humans: int
    names: list[str]
    speaking: list[str]
    state: str  # in_call | removed | ended


class MeetSession:
    def __init__(self, page: Page, events: Events, display_name: str, consent_text: str,
                 lobby_timeout_s: int = 180) -> None:
        self.page = page
        self.events = events
        self.display_name = display_name
        self.consent_text = consent_text
        self.lobby_timeout_s = lobby_timeout_s

    # -- login -------------------------------------------------------------------------------

    def is_logged_in(self) -> bool:
        self.page.goto("https://meet.google.com/", wait_until="domcontentloaded")
        self.page.wait_for_timeout(2000)
        return "accounts.google.com" not in self.page.url

    def login(self, email: str, password: str) -> None:
        self.page.goto("https://accounts.google.com/ServiceLogin?continue=https://meet.google.com/",
                       wait_until="domcontentloaded")
        try:
            self.page.fill(S.LOGIN_EMAIL, email)
            self.page.click(S.LOGIN_NEXT)
            self.page.wait_for_selector(S.LOGIN_PASSWORD, state="visible", timeout=15000)
            self.page.fill(S.LOGIN_PASSWORD, password)
            self.page.click(S.LOGIN_NEXT)
            self.page.wait_for_timeout(4000)
        except PWTimeout as exc:
            raise BotError("login_form_not_found") from exc
        if self.page.locator(S.LOGIN_2SV_HINT).count():
            raise BotError("2sv_required")
        if "accounts.google.com" in self.page.url:
            raise BotError("login_rejected")
        self.events.emit("logged_in", email=email)

    # -- join --------------------------------------------------------------------------------

    def _click_if_present(self, selector: str, timeout_ms: int = 1500) -> bool:
        loc = self.page.locator(selector).first
        try:
            loc.wait_for(state="visible", timeout=timeout_ms)
            loc.click()
            return True
        except PWTimeout:
            return False

    def _ensure_muted(self, selector: str) -> None:
        loc = self.page.locator(selector).first
        try:
            loc.wait_for(state="visible", timeout=5000)
        except PWTimeout:
            return  # no device offered, nothing to mute
        if loc.get_attribute("data-is-muted") != "true":
            loc.click()

    def join(self, url: str) -> str:
        """Returns joined | not_admitted | denied."""
        self.page.goto(url, wait_until="domcontentloaded")
        self._click_if_present(S.PREJOIN_CONTINUE_WITHOUT_MEDIA, 4000)
        self._ensure_muted(S.PREJOIN_MIC_BUTTON)
        self._ensure_muted(S.PREJOIN_CAM_BUTTON)
        name = self.page.locator(S.PREJOIN_NAME_INPUT).first
        if name.count() and name.is_visible():
            name.fill(self.display_name)

        if self._click_if_present(S.PREJOIN_JOIN_NOW, 8000):
            self.events.emit("join_clicked", mode="join_now")
        elif self._click_if_present(S.PREJOIN_ASK_TO_JOIN, 3000):
            self.events.emit("join_clicked", mode="ask_to_join")
        else:
            raise BotError("join_button_not_found")

        deadline = time.time() + self.lobby_timeout_s
        lobby_seen = False
        while time.time() < deadline:
            if self.page.locator(S.IN_CALL_LEAVE).count():
                self.events.emit("joined", lobby=lobby_seen)
                return "joined"
            if self.page.locator(S.LOBBY_DENIED).count():
                self.events.emit("denied")
                return "denied"
            if not lobby_seen and self.page.locator(S.LOBBY_WAITING).count():
                lobby_seen = True
                self.events.emit("in_lobby")
            self.page.wait_for_timeout(1000)
        self.events.emit("not_admitted", waited_s=self.lobby_timeout_s)
        return "not_admitted"

    # -- consent (AC-S1-2) -------------------------------------------------------------------

    def post_consent(self) -> None:
        if not self._click_if_present(S.CHAT_OPEN, 8000):
            self.events.emit("consent_skipped", reason="chat_button_not_found")
            return
        try:
            box = self.page.locator(S.CHAT_INPUT).first
            box.wait_for(state="visible", timeout=8000)
            box.fill(self.consent_text)
            if not self._click_if_present(S.CHAT_SEND, 1500):
                box.press("Enter")
            self.events.emit("consent_posted")
        except PWTimeout:
            self.events.emit("consent_skipped", reason="chat_input_not_found")
        self._click_if_present(S.CHAT_CLOSE, 1500)

    def open_people_panel(self) -> None:
        if self._click_if_present(S.PEOPLE_OPEN, 5000):
            self.page.wait_for_timeout(1000)

    # -- polling (AC-S1-6, AC-S1-7, AC-S1-8) -------------------------------------------------

    def poll(self) -> Poll:
        if self.page.locator(S.IN_CALL_REMOVED).count():
            return Poll(0, [], [], "removed")
        if self.page.locator(S.IN_CALL_ENDED).count() or not self.page.locator(S.IN_CALL_LEAVE).count():
            return Poll(0, [], [], "ended")
        names = [
            (item.get_attribute("aria-label") or item.inner_text() or "").strip()
            for item in self.page.locator(S.PEOPLE_LIST_ITEM).all()
        ]
        humans = [n for n in names if n and S.PEOPLE_SELF_MARK not in n]
        speaking = self.page.evaluate(
            """([tile, nameAttr, speakingSel]) => Array.from(document.querySelectorAll(tile))
                 .filter(t => t.querySelector(speakingSel))
                 .map(t => t.getAttribute(nameAttr) || t.getAttribute('aria-label') || '')
                 .filter(Boolean)""",
            [S.TILE, S.TILE_NAME_ATTR, S.TILE_SPEAKING],
        )
        return Poll(len(humans), humans, speaking, "in_call")

    def leave(self) -> None:
        self._click_if_present(S.IN_CALL_LEAVE, 3000)
        self.events.emit("left")
