"""CLI. One process = one meeting.

  python -m bot --meet-url https://meet.google.com/abc-defg-hij --display-name "Notetaker (for Jayson)" --out /out/run1
  python -m bot --login-only            # opens accounts.google.com on the Xvfb display + VNC on :5900

Exit 0 with reason on stdout: joined | room_empty | removed | ended | max_duration | not_admitted | denied.
Exit 1 with reason error:<what> and last screenshot uploaded (AC-S1-9).
"""
from __future__ import annotations

import argparse
import json
import signal
import os
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from .events import Events
from .meet import BotError, MeetSession
from .recorder import Recorder
from .storage import Storage

DEFAULT_CONSENT = (
    "Notetaker is recording audio for meeting minutes on behalf of {user}. "
    "Ask the organiser to remove it if you do not consent."
)
LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--autoplay-policy=no-user-gesture-required",
    "--window-size=1280,720",
    "--window-position=0,0",
    "--lang=en-US",
    "--disable-gpu",
    "--disable-extensions",
    "--disable-background-networking",
]
HEADLESS = os.environ.get("BOT_HEADLESS", "1") == "1"  # BOT_HEADLESS=0 -> Xvfb, if Meet refuses headless


def parse() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--meet-url")
    p.add_argument("--display-name", default=os.environ.get("BOT_DISPLAY_NAME", "Notetaker"))
    p.add_argument("--for-user", default=os.environ.get("BOT_FOR_USER", ""))
    p.add_argument("--consent-text", default=os.environ.get("BOT_CONSENT_TEXT"))
    p.add_argument("--out", default=os.environ.get("BOT_OUT", "/out"))
    p.add_argument("--profile", default=os.environ.get("BOT_PROFILE_DIR", "/profile"))
    p.add_argument("--lobby-timeout", type=int, default=int(os.environ.get("BOT_LOBBY_TIMEOUT", "180")))
    p.add_argument("--empty-room-seconds", type=int, default=int(os.environ.get("BOT_EMPTY_ROOM_SECONDS", "60")))
    p.add_argument("--min-seconds", type=int, default=int(os.environ.get("BOT_MIN_SECONDS", "60")))
    p.add_argument("--max-seconds", type=int, default=int(os.environ.get("BOT_MAX_SECONDS", str(4 * 3600))))
    p.add_argument("--login-only", action="store_true")
    a = p.parse_args()
    if not a.login_only and not a.meet_url:
        p.error("--meet-url is required unless --login-only")
    return a


def launch(pw, profile: str, headless: bool = HEADLESS):
    channel = os.environ.get("BOT_BROWSER_CHANNEL") or None  # "chrome" on amd64, Chromium on arm64
    args = LAUNCH_ARGS + (["--headless=new"] if headless else [])
    return pw.chromium.launch_persistent_context(
        user_data_dir=profile,
        headless=False,  # Playwright's own headless swaps in a stripped shell; we pass --headless=new ourselves
        channel=channel,
        args=args,
        ignore_default_args=["--enable-automation"],
        viewport={"width": 1280, "height": 720},
        locale="en-US",
    )


def login_only(profile: str) -> int:
    vnc = subprocess.Popen(["x11vnc", "-display", os.environ.get("DISPLAY", ":99"), "-forever", "-nopw",
                            "-rfbport", "5900", "-quiet"])
    print("VNC on :5900. Log in to Google in the browser, then stop this container.", flush=True)
    with sync_playwright() as pw:
        ctx = launch(pw, profile, headless=False)  # login needs a screen: 2SV prompt over VNC
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://accounts.google.com/ServiceLogin?continue=https://meet.google.com/")
        try:
            while True:
                time.sleep(5)
                if "accounts.google.com" not in page.url and "meet.google.com" in page.url:
                    print("Logged in. Profile saved. Waiting 15 s for cookies to flush.", flush=True)
                    time.sleep(15)
                    break
        except KeyboardInterrupt:
            pass
        ctx.close()
    vnc.terminate()
    return 0


STOP = {"requested": False}


def _request_stop(signum, frame):  # SIGTERM from docker stop / run.sh stop: leave the call, do not vanish
    STOP["requested"] = True


def run(a: argparse.Namespace) -> int:
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    work = Path("/tmp/botwork")
    work.mkdir(parents=True, exist_ok=True)
    storage = Storage(a.out)
    events = Events(work / "events.jsonl")
    consent = a.consent_text or DEFAULT_CONSENT.format(user=a.for_user or a.display_name)
    display_name = a.display_name if not a.for_user else f"{a.display_name} (for {a.for_user})"
    recorder = Recorder(work, storage)
    reason = "error:unknown"
    code = 1
    page = None

    def finish() -> None:
        n = recorder.stop()
        events.emit("finished", reason=reason, segments=n)
        events.close()
        storage.put(work / "events.jsonl")

    with sync_playwright() as pw:
        ctx = launch(pw, a.profile)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        session = MeetSession(page, events, display_name, consent, a.lobby_timeout)
        try:
            if not session.is_logged_in():
                email, password = os.environ.get("BOT_EMAIL"), os.environ.get("BOT_PASSWORD")
                if not (email and password):
                    raise BotError("not_logged_in_and_no_credentials")
                session.login(email, password)

            outcome = session.join(a.meet_url)
            if outcome != "joined":
                reason, code = outcome, 0
                return code  # finally still runs finish()

            recorder.start()
            events.emit("recording_started")
            session.post_consent()
            probe_at = time.time() + 20  # first DOM probe once tiles have settled

            started = time.time()
            empty_since: float | None = None
            last_names: list[str] = []
            last_humans = -1
            while True:
                if STOP["requested"]:
                    reason = "stopped"
                    break
                p = session.poll()
                if p.state == "removed":
                    reason = "removed"
                    break
                if p.state == "ended":
                    reason = "ended"
                    break
                if p.names != last_names or p.humans != last_humans:
                    events.emit("participants", humans=p.humans, tiles=p.names)
                    last_names, last_humans = p.names, p.humans
                if p.speaking:
                    events.emit("active_speaker", names=p.speaking)
                if p.humans == 0 and time.time() - started > a.min_seconds:
                    empty_since = empty_since or time.time()
                    if time.time() - empty_since >= a.empty_room_seconds:
                        reason = "room_empty"
                        break
                else:
                    empty_since = None
                if time.time() - started >= a.max_seconds:
                    reason = "max_duration"
                    break
                if time.time() >= probe_at:
                    probe = session.dom_probe()
                    (work / "dom_probe.json").write_text(json.dumps(probe, indent=1, ensure_ascii=False))
                    storage.put(work / "dom_probe.json")
                    page.screenshot(path=str(work / "in_call.png"))
                    storage.put(work / "in_call.png")
                    events.emit("dom_probe", buttons=len(probe["buttons"]), listitems=len(probe["listitems"]), tiles=len(probe["tiles"]))
                    probe_at = time.time() + 60
                time.sleep(1)
            session.leave()
            code = 0
        except BotError as exc:
            reason = f"error:{exc}"
        except Exception as exc:  # noqa: BLE001 - spike: any crash must leave a reason + screenshot
            reason = f"error:{type(exc).__name__}:{str(exc)[:120]}"
        finally:
            if code != 0 and page is not None:
                shot = work / "last.png"
                try:
                    page.screenshot(path=str(shot), full_page=False)
                    storage.put(shot)
                except Exception:  # noqa: BLE001
                    pass
            finish()
            ctx.close()
    print(reason, flush=True)
    return code


if __name__ == "__main__":
    args = parse()
    sys.exit(login_only(args.profile) if args.login_only else run(args))
