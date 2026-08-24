#!/usr/bin/env bash
# Spike helper. Usage:
#   ./run.sh build
#   ./run.sh login                      # then open vnc://localhost:5900 (macOS Screen Sharing), log in, Ctrl-C
#   ./run.sh join https://meet.google.com/xxx-yyyy-zzz "Jayson"   # records to ./out/<timestamp>/
set -euo pipefail
cd "$(dirname "$0")"
IMG=foundryx-shared-service:bot-spike
PROFILE="$PWD/.profile"; OUT="$PWD/out"; mkdir -p "$PROFILE" "$OUT"
case "${1:-}" in
  build) docker build -t "$IMG" . ;;
  login) docker run --rm -it -p 5900:5900 -v "$PROFILE:/profile" "$IMG" --login-only ;;
  join)
    RUN="$OUT/$(date +%Y%m%d-%H%M%S)"; mkdir -p "$RUN"
    NAME="bot-$(basename "$RUN")"
    ( while docker stats --no-stream --format '{{.MemUsage}} {{.CPUPerc}}' "$NAME" 2>/dev/null; do sleep 15; done ) >> "$RUN/stats.log" &
    docker run --rm --name "$NAME" -v "$PROFILE:/profile" -v "$RUN:/out" --shm-size=1g -e BOT_HEADLESS="${BOT_HEADLESS:-1}" \
      "$IMG" --meet-url "$2" --display-name Notetaker --for-user "${3:-}" --out /out ;;
  *) echo "usage: $0 build|login|join <url> [for-user]"; exit 2 ;;
esac
