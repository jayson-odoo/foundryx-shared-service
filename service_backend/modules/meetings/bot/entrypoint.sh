#!/usr/bin/env bash
# Boots the audio sink and the virtual display, then hands over to the bot.
set -euo pipefail

pulseaudio -D --exit-idle-time=-1 --log-target=stderr 2>/dev/null || true
for _ in $(seq 1 20); do pactl info >/dev/null 2>&1 && break; sleep 0.25; done
pactl load-module module-null-sink sink_name="${PULSE_SINK}" sink_properties=device.description="${PULSE_SINK}" >/dev/null
pactl set-default-sink "${PULSE_SINK}"

# Headless by default (BOT_HEADLESS=1). A screen only for the one-time login or the Xvfb fallback.
if [[ "${BOT_HEADLESS:-1}" != "1" || " $* " == *" --login-only "* ]]; then
  Xvfb "${DISPLAY}" -screen 0 1280x720x24 -nolisten tcp >/dev/null 2>&1 &
  for _ in $(seq 1 20); do xdpyinfo -display "${DISPLAY}" >/dev/null 2>&1 && break; sleep 0.25; done
fi

exec python -m bot "$@"
