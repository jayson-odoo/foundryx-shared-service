#!/usr/bin/env bash
# Meetings S3 (R6, AC-S3-13) - creates/pins the DEDICATED python venv the
# mlx-whisper STT driver execs into (never the backend's own venv: mlx needs
# its own Metal-linked dependency set and a different Python than the
# backend runs). Idempotent - a re-run on an already-built venv is a no-op,
# so a reboot or a fresh host rebuilds it deterministically.
#
# Usage: scripts/setup_stt_venv.sh
# Env overrides: STT_VENV_DIR (default ~/foundryx-stt/venv), STT_PYTHON_BIN
# (default python3), MLX_WHISPER_VERSION (default 0.4.3, pinned per R6).
set -euo pipefail

STT_VENV_DIR="${STT_VENV_DIR:-$HOME/foundryx-stt/venv}"
STT_PYTHON_BIN="${STT_PYTHON_BIN:-python3}"
MLX_WHISPER_VERSION="${MLX_WHISPER_VERSION:-0.4.3}"

if [ ! -x "${STT_VENV_DIR}/bin/python" ]; then
  echo "Creating STT venv at ${STT_VENV_DIR}"
  "${STT_PYTHON_BIN}" -m venv "${STT_VENV_DIR}"
else
  echo "STT venv already exists at ${STT_VENV_DIR}"
fi

"${STT_VENV_DIR}/bin/pip" install --upgrade pip --quiet
"${STT_VENV_DIR}/bin/pip" install "mlx-whisper==${MLX_WHISPER_VERSION}" --quiet

echo "mlx-whisper ${MLX_WHISPER_VERSION} ready: ${STT_VENV_DIR}/bin/python"
