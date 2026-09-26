#!/bin/sh
set -eu
cd "$(dirname "$0")"
export PYTHONUTF8=1
export QUESTION_BANK_DATA="${QUESTION_BANK_DATA:-$PWD/data}"
export QUESTION_BANK_MATERIALS_DIR="${QUESTION_BANK_MATERIALS_DIR:-$PWD/materials}"
if [ -f "$QUESTION_BANK_DATA/bank.sqlite" ]; then
  export QUESTION_BANK_NO_BACKGROUND_DB_WRITES=1
else
  export QUESTION_BANK_NO_BACKGROUND_DB_WRITES=0
fi
export QUESTION_BANK_PDF_IMPORT_PROFILE="${QUESTION_BANK_PDF_IMPORT_PROFILE:-pure_d_light_review_v1}"
mkdir -p "$QUESTION_BANK_DATA" "$QUESTION_BANK_MATERIALS_DIR"
exec .venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port "${QUESTION_BANK_PORT:-8765}" --no-access-log
