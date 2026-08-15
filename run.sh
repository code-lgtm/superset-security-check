#!/usr/bin/env bash
set -a
source .env
set +a

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
pip install -r requirements.txt
python webhook.py
