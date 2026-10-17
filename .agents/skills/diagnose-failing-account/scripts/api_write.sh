# vendored from workspace/.agents/skills/diagnose-failing-account/scripts/api_write.sh — do not edit; run `python scripts/sync.py agents`
#!/usr/bin/env bash
# POST/PUT/DELETE a Litmus API route with the bearer key from $LITMUS_API_KEY; never prints the key.
# Every write carries a fresh Idempotency-Key (reuse one on purpose only to retry the same request).
# usage: api_write.sh POST /v1/<unit>/resources/<r>/sync '{"no_fetch": true}'
#        api_write.sh POST /v1/cex/resources/<r>/edits @edit.json            (a JSON file)
#        api_write.sh POST /v1/cex/resources/<r>/uploads -F 'files=@export.csv'  (multipart)
# env: LITMUS_API (default http://localhost:8080), LITMUS_API_KEY (required).
set -euo pipefail
method=${1:?usage: api_write.sh METHOD /v1/... [json|@file|curl args]}; path=${2:?route}; shift 2
: "${LITMUS_API_KEY:?set LITMUS_API_KEY}"
body=()
if [[ $# -gt 0 && $1 != -* ]]; then
  body=(-H 'Content-Type: application/json' --data-binary "$1"); shift
fi
curl -fsS -X "$method" --config <(printf 'header = "Authorization: Bearer %s"\n' "$LITMUS_API_KEY") \
  -H "Idempotency-Key: diag-$(date +%s%N)-$RANDOM" "${body[@]}" \
  "${LITMUS_API:-http://localhost:8080}$path" "$@"
