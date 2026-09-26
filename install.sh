#!/bin/sh
set -eu
cd "$(dirname "$0")"
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock -r requirements-d-shadow.lock
cd frontend
npm ci
npm run build
