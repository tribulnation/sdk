# vendored from workspace/.agents/skills/diagnose-failing-account/scripts/db_payloads.sh — do not edit; run `python scripts/sync.py agents`
#!/usr/bin/env bash
# DB fallback: dump the served payloads (verification, items, state, compartments) of one unit resource
# into <out>/<resource>-<payload>.json. SELECT only; credential tables are never touched.
# usage: db_payloads.sh <unit: evm|cex|hl|dydx> <resource name> [out dir]
# env: PG_CONTAINER (default litmus-local-postgres-1), PG_USER (default litmus_admin).
set -euo pipefail
unit=${1:?unit}; name=${2:?resource name}; out=${3:-.}
mkdir -p "$out"
for p in verification items state compartments; do
  # psql variables are interpolated only in scripts read from stdin, not in -c
  echo "SELECT p.body FROM state.payloads p JOIN litmus_resources r USING (resource_id) WHERE r.name = :'name' AND p.name = :'payload'" \
    | docker exec -i "${PG_CONTAINER:-litmus-local-postgres-1}" psql -U "${PG_USER:-litmus_admin}" -d "litmus_$unit" -At \
      -v name="$name" -v payload="$p" > "$out/$name-$p.json"
  echo "$out/$name-$p.json $(wc -c < "$out/$name-$p.json") bytes"
done
