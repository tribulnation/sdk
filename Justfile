RUFF := ".venv/bin/ruff"

help:
  @just --list

format PATH='./packages':
  {{RUFF}} format {{PATH}}

check PATH='./packages':
  {{RUFF}} check {{PATH}}
