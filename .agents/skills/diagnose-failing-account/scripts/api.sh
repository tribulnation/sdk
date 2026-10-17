# vendored from workspace/.agents/skills/diagnose-failing-account/scripts/api.sh — do not edit; run `python scripts/sync.py agents`
#!/usr/bin/env bash
# GET a Litmus API route with the bearer key from $LITMUS_API_KEY; never prints the key.
# usage: api.sh /v1/<unit>/resources/<r>/verification [curl args...]
# env: LITMUS_API (default http://localhost:8080), LITMUS_API_KEY (required).
set -euo pipefail
path=${1:?usage: api.sh /v1/<unit>/... [curl args]}; shift
: "${LITMUS_API_KEY:?set LITMUS_API_KEY}"
curl -fsS -G --config <(printf 'header = "Authorization: Bearer %s"\n' "$LITMUS_API_KEY") \
  "${LITMUS_API:-http://localhost:8080}$path" "$@"
