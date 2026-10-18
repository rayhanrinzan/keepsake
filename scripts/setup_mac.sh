#!/usr/bin/env bash
# One-time Keepsake setup on a Mac: Python venv, web app, Photon agent, hand model.
# Safe to re-run. Never overwrites an existing .env. Usage: bash scripts/setup_mac.sh
set -euo pipefail
cd "$(dirname "$0")/.."

PY=""
for p in python3.12 python3.13 python3.11; do command -v "$p" >/dev/null && { PY=$p; break; }; done
[ -n "$PY" ] || { echo "Need Python 3.11-3.13 (brew install python@3.12)"; exit 1; }
command -v npm >/dev/null || { echo "Need Node.js 20+ (brew install node)"; exit 1; }

echo "==> Python venv ($PY)"
[ -x .venv/bin/python ] || "$PY" -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r backend/requirements.txt mediapipe

echo "==> Hand model"
[ -f backend/models/hand_landmarker.task ] || curl -sSL -o backend/models/hand_landmarker.task \
  https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task

echo "==> Web app and Photon agent"
npm --prefix frontend install --silent
npm --prefix integrations/photon install --silent

for f in .env integrations/photon/.env; do
  if [ -f "$f" ]; then echo "    $f already there (kept)"
  else cp "${f%.env}.env.example" "$f"; chmod 600 "$f"; echo "    created $f from the example: fill it in"; fi
done

echo "==> Cameras macOS sees (pick the iPhone's name for CTRLF_CAMERA_NAME)"
(cd backend && ../.venv/bin/python check_camera.py) || true
echo "Done. Next: docs/demo_on_another_mac.md"
