# Meetings S1 bot: one container = one meeting. See PLAN-meetings-s1-bot-spike.md.
FROM mcr.microsoft.com/playwright/python:v1.62.0-noble

RUN apt-get update \
 && apt-get install -y --no-install-recommends xvfb pulseaudio pulseaudio-utils ffmpeg x11vnc \
 && rm -rf /var/lib/apt/lists/*

# Real Chrome exists for amd64 only; on arm64 this is a no-op and Playwright's Chromium is used.
RUN playwright install chrome || true

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY entrypoint.sh .
COPY bot ./bot
RUN chmod +x entrypoint.sh && mkdir -p /profile /out

ENV DISPLAY=:99 \
    PULSE_SINK=meet \
    BOT_PROFILE_DIR=/profile \
    BOT_OUT=/out

ENTRYPOINT ["/app/entrypoint.sh"]
