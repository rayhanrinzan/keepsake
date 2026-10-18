#!/bin/zsh
cd "$(dirname "$0")/.." && exec .venv/bin/python legacy/lastseen_demo.py "$@"
