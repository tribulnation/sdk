RUFF := ".venv/bin/ruff"

help:
  @just --list

format PATH='./packages':
  {{RUFF}} format {{PATH}}

check PATH='./packages':
  {{RUFF}} check {{PATH}}

# Render docs/contract/*.yml into a landing checkout and refresh its own render step, so
# a local `yarn dev` picks up the change via Vite HMR — no server restart needed.
docs-refresh LANDING='refs/landing':
  .venv/bin/sdk-dev docs sync --path {{LANDING}}
  cd {{LANDING}} && node scripts/render-docs.mjs
