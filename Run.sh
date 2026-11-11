#!/bin/sh
cd "$(dirname "$0")"
# Prefer Python 3.12, which the README requires; fall back to the default python3.
if command -v python3.12 >/dev/null 2>&1; then exec python3.12 Main.py; fi
exec python3 Main.py
