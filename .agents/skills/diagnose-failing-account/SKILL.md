---
name: diagnose-failing-account
description: Diagnose a Litmus account whose unit audit (verification checkpoints) is `failed` or `unassessable`, find the root cause (code bug, spec error, missing spec, missing owner data, or unassessable by design) and drive the fix. Use when an evm address, cex account, Hyperliquid or dYdX account shows a non-verified audit in the portfolio or a unit's `/verification`, when asked why an account fails, or when checking that a `verified` account is not vacuously verified.
---
<!-- vendored from workspace/.agents/skills/diagnose-failing-account/SKILL.md — do not edit; run `python scripts/sync.py agents` -->

# Diagnose a failing account

The job: an account's audit is `failed` or `unassessable`. Find **why**, **classify** it, and
**remove the cause** or hand the owner an exact action. Units: evm, cex, hl, dydx. Read the unit's
reference file before starting: [evm.md](evm.md), [cex.md](cex.md), [hl.md](hl.md),
[dydx.md](dydx.md).

## Hard rules

1. **Read-only on the stack** unless the owner has granted you admin for this task. Without it: only
   `GET`s on the API (or `SELECT`s on the DB fallback). No `POST` sync/verification/edits/uploads, no
   container restarts, no DB writes. Propose those actions instead.
2. **Never print credentials.** Keep the API key in an env var (`LITMUS_API_KEY`), never echo it or
   put it in a file, issue or PR. Skip credential columns and tables (`litmus_credentials`) in
   SELECTs. Check a capture body before printing it.
3. **Never invent legs, observations or snapshots to force a pass.** An edit must be backed by
   evidence you can cite (another export, a chain read). If the evidence does not exist, the
   interval stays failed/unassessable and the owner gets a data action.
4. **Narrower reruns must not destroy retained observations.** Never run (or recommend) a
   verification/sync with fewer checks (`no_bank`, `offline`, a smaller height set) over heights
   that already have a richer observation. If you find one did, that is a code bug (see dydx#28).
5. Public external sources (explorers, RPCs, venue public endpoints) are fine, **sparingly**. Paid
   provider keys only when the owner allows it.
6. Code fixes go through a worktree and a PR on the unit repo, never merged by you unless your
   review mode says so. Specs changes go through an issue on `litmus-tax/specs`; never edit specs
   `main`.

## Access

```sh
API=${LITMUS_API:-http://localhost:8080}
export LITMUS_API_KEY="$(cat <key file the owner issued>)"   # never echo it
get() { curl -fsS -H "Authorization: Bearer $LITMUS_API_KEY" "$API$1"; }   # or scripts/api.sh
```

Authenticate with an API key the owner issues you (tenant, scopes and audiences chosen by them),
read from a file. Never mint tokens yourself from the platform's signing keys, even locally: it
bypasses the owner's grant, and a platform upgrade breaks the script anyway (it did on 2026-09-29).
The platform now runs inside the combined api (`litmus-runtime`); routes keep their `/v1/<service>`
prefixes.

Reads (verified on the local stack 2026-09-29; `{r}` is the resource **id**, not its name). Lists
page with `limit` (at most 500) and `cursor=<next_cursor>`, passing the same filters again:

| What | API (preferred) | DB fallback (`litmus_<unit>`) |
|---|---|---|
| Accounts, their resources, coverage | `GET /v1/portfolio/portfolios/{p}/accounts[/{account}]` | `litmus_portfolio`: `accounts`, `account_resources`, `coverage` |
| Resources of a unit (id, name, binding) | `GET /v1/<unit>/resources?limit=100` → `items[]` | `public.litmus_resources` (`name, resource_id, binding`) |
| Served audit | `GET /v1/<unit>/resources/{r}/verification` | `state.payloads WHERE name='verification'` |
| Open items | `GET /v1/<unit>/resources/{r}/items?limit=200` (an item may carry `resolve.request_template`, a ready edit body) | `state.payloads WHERE name='items'` |
| Records | `…/records?from=&to=&kind=&compartment=&limit=` → `records[]` | `state.records` |
| State at an instant | `…/state?at=<RFC 3339>` (the parameter is **`at`**; an unknown one is ignored and the head state comes back) | `state.payloads` |
| Evidence object, by digest | `…/evidence/{digest}` (raw bytes; also serves cex `book/evidence/index.json`, which maps evidence **ids** to names and digests) | unit-specific (see reference) |
| Export coverage (cex) | `…/coverage` | — |
| Stored credentials (status only) | `…/credentials` → `configured`, `last_used_at`, `last_error` (the auto-mode classifier may refuse this read; a sync job's `result.snapshot` gives the capture outcome instead) | never read `litmus_credentials` |
| Jobs | `GET /v1/<unit>/jobs?resource={r}`, `GET /v1/<unit>/jobs/{job}` (`status`, `error`, `result`); portfolio `GET /v1/portfolio/jobs/{job}` | `public.litmus_jobs` |
| Portfolio items | `GET /v1/portfolio/portfolios/{p}/items?limit=` → `counts` by kind (`dangling_link`, `unmatched_transfer`, `unsolicited_receipt`, …) | `litmus_portfolio` |
| Portfolio records | `GET …/{p}/records?account=&from=&to=&limit=` (`from`/`to`; unknown names are ignored) → `records[].event` with `type`, `src_network(_id)`, `dst_network(_id)`, `correlation` | `litmus_portfolio` |
| Portfolio links | `GET …/{p}/links?account=&kind=&limit=` → `id, kind, reason` (the pass), `withdrawal`/`deposit` with `record` ids | `litmus_portfolio` |
| Unmatched legs | `GET …/{p}/unmatched?account=&asset=&nearest=N&limit=` → `legs[]`, each with `record` and `nearest[]` counterparts plus the `reasons` they did not link (`type`, `asset`, `network`, `tx_id`, `amount`, `window`, …) | `litmus_portfolio` |
| Ledger history | `GET …/{p}/history` | `litmus_portfolio` |

Writes (only with an admin grant). Every POST needs an `Idempotency-Key` header, a fresh one per
attempt (`scripts/api_write.sh` adds it). Each returns `202 {job}`; poll the job:

| What | Route and body |
|---|---|
| Sync (fetch) | `POST …/resources/{r}/sync` `{}`; evm `{fetch, full, to_height, …}`, dydx `{verify_at: [h…], no_bank, offline, …}`, cex `{no_fetch}` |
| Re-derive only | evm `{"fetch": false}`, hl `{"fetch": false, "archive": false}`, dydx `{"offline": true}`, cex `{"no_fetch": true}` |
| Verify at heights (dydx) | `POST …/resources/{r}/verification` `{"height": [h…]}` (bank stays on; hard rule 4) |
| Stage an edit | `POST …/resources/{r}/edits`, one edit per call; `?apply=true` on the **last** starts the sync that applies every pending edit; `GET …/edits?all=true`; `DELETE …/edits/{e}` withdraws |
| Preview an edit | `POST …/resources/{r}/edits/preview` `{"add": <edit>}` or `{"withdraw": "<edit id>"}` → a job whose `result` has `verification.status_before/after`, `items.resolved/added` and record diffs (cex: not for `add_evidence`) |
| Upload evidence (cex) | `POST …/resources/{r}/uploads`, multipart `files=@…` (optional `parser=venue/name`) → per-file `detection` (`recognised`, `duplicate`, `unrecognised` + reason); then an `add_evidence` edit (cex.md) |
| Credentials | `PUT …/resources/{r}/credentials` with the venue's fields: one test call, then sealed. Read the secrets from the owner's env file inside the script; never print them |
| Portfolio | `POST /v1/portfolio/portfolios/{p}/sync` `{"refresh": false}` imports (`result.links.{total, dangling}`) but does **not** re-link machine pairs (verified 2026-09-30: `/unmatched` showed the new pairs with no reasons, links unchanged); `POST …/{p}/reconcile` `{}` re-links (`result.{links, by_pass, unmatched, candidates}`); `POST …/{p}/rebuild` `{"refresh": false}` re-reconciles from scratch, and `result.rebuild.reconcile.{links, candidates, unmatched, unsolicited}` are the reconciliation counts |

1. A sync that only applies edits (`?apply=true`) does not capture: run a separate fetching sync.
2. A resource not synced since a catalogue or code release still serves the old derivation (MEXC
   still had its pre-cex#60 trade times): re-derive before reading times or signs.
3. Superseding evidence changes record ids, so the next portfolio sync reports `dangling_link`
   items; a rebuild clears them.
4. `DELETE …/edits/{e}?apply=true` on an applied edit returns the edit with its **original** `job`.
   The withdrawal's sync is `withdrawal.job` (`GET …/edits?all=true`, or the newest entry of
   `GET …/jobs?resource=`). Wait on that one, then check `status: withdrawn`.
5. An empty `reasons` list on an `/unmatched` counterpart does **not** prove a pass would link the
   pair. The route checks the loosest rung (30 days after, 1 hour before), while the bridge passes
   stop at 1 day and also compare `src_network_id`/`dst_network_id`, which `/unmatched` did not
   flag as of portfolio 744e6b7 (2026-09-29). Compare the two records' network fields before
   calling a pair "linkable".
6. API 500/502 errors with no application traceback, or `connection failed … not yet accepting
   connections`: look at `docker logs litmus-local-postgres-1` for crash recovery before blaming
   the route. Wait for "ready to accept connections"; never restart containers.
7. To explain a change in reconciliation counts, compare against the **dated** rebuild that
   produced the baseline (`result.rebuild.reconcile` of that job, plus a links dump), not "this
   morning". Map records by tx hash, because unit record ids can change (superseded evidence, log
   indexes).
8. An unmatched leg whose counterpart is **another owner address on the same network** (same tx
   hash) but `nearest` does not list it: the counterpart's resource was not *fetched* after the
   tx. A sync job's `params` read `{}` for both kinds; a re-derive has no `discover …` lines in
   its `progress`, and `…/records?from=&to=` shows a `coverage.gaps[{reason: unattested}]` from
   the last fetch. A fetching sync of that resource, a portfolio sync and a reconcile link it by
   `tx_ids.match` (2026-09-30: ethereum1-arbitrum was last fetched 09:25, the 16:25 gas top-up
   to ethereum3 linked after one).

DB fallback: `docker exec litmus-local-postgres-1 psql -U litmus_admin -d <db> -At -c "SELECT …"`.
Reference queries use psql variables (`:'res'`); those only interpolate from stdin:
`echo "<sql>" | docker exec -i litmus-local-postgres-1 psql -U litmus_admin -d <db> -At -v res=<name>`.

Scripts (in `scripts/`, stdlib only, no secrets):

1. `api.sh <route> [curl args]`: authenticated GET, key from `$LITMUS_API_KEY`, never echoed.
   `api_write.sh METHOD <route> [json|@file] [curl args]`: the same for writes, with a fresh
   `Idempotency-Key` (admin grant only).
2. `db_payloads.sh <unit> <resource> [dir]`: dumps a resource's served payloads (DB fallback).
3. `checkpoints.py <verification.json|->`: one line per failing `(compartment, asset)` with its trend.
4. `nonce_bisect.py <rpc> <address> <n> <lo> <hi>`: which block/tx consumed an EVM nonce.

## Flow

### 1. Locate the failing checkpoints

1. Map the account to its unit resources (one account can have several: evm has one per network;
   any failing resource fails the account).
2. Pull `…/verification` for each. The shape is shared by all units:
   `status`, `intervals[{from,to,status}]`, `checkpoints[{at, compartment, asset, expected,
   observed, delta, tolerance, status, reason, evidence}]`, `detail` (unit-specific).
3. `scripts/api.sh /v1/<unit>/resources/{r}/verification | python3 scripts/checkpoints.py -` prints
   one line per failing `(compartment, asset)`: count, range, last expected/observed, and whether
   the delta is **constant, growing, shrinking or erratic**. `accepted` = within tolerance, not a failure.
4. Read the **type** of non-pass before anything else:
   1. `delta` over `tolerance` → a real mismatch. `delta = observed − expected`: positive = an inflow
      is missing from the records, negative = an outflow (or fee) is missing.
   2. `observed: null` → nothing was observed. Not a mismatch: find the raw observation; if it exists,
      the comparison was lost (code bug).
   3. `status: unassessable` with all checkpoints passed → something outside the balance identity:
      unattested history, discovery gaps, half-attributed moves. Read `detail` and the items.
5. Pull `…/items`. Error-severity items explain most verdicts; info items (spam, unsolicited) rarely do.

### 2. Get ground truth independently

Never trust the unit's arithmetic or its observation on its own. For each failing
`(compartment, asset, at)`, get the true balance and/or the true history from a source the unit
did not produce, or re-derive it from the raw evidence (see the reference file for each unit's
sources and costs). Confirm the **observed** side first: if the observation itself is wrong, the
rest is moot.

**Third-party balance records** (an old tracker's CSV, a portfolio tool's export) are strong
localisers once their accuracy is proved.
1. **Validate first** on accounts the unit already verifies: compare each record with
   `…/state?at=<its timestamp>` of a passing resource. Sum the compartments per asset, leaving out
   `:debt`, opaque compartments and `unattributed`. Also compare with the chain's `balanceOf`
   at the block of that timestamp.
2. **Then trust it**: a record that matches to the base unit (160/160 bitget instants, and aTokens
   whose balance moves every block) is a verbatim API reader with true timestamps.
3. **Localise the residual**: for the failing account, the per-instant difference `record − replay`
   dates every missing flow: a step is one event, a drift a recurring one (fit funding with the
   venue's public funding history).
4. **What the book may take from it**: see cex.md. Its checkpoints are not admitted today (specs#53).

### 3. Recompute

Rebuild `expected` from the raw inputs (exports, retained txs, fills) with a short script in the
scratchpad. Then:

1. Your recomputation = unit's `expected` → the parsing/replay is right; the residual is **missing
   inputs** or a **wrong observation**.
2. They differ → diff per record kind; the difference is a **code or spec** problem.

### 4. Attribute the residual

1. **Constant delta** across checkpoints → one event before the first checkpoint.
2. **Growing delta** → a recurring cause (rewards, funding, fees, rebasing, a feed that keeps missing
   things). Divide the residual by the candidate periodic amount; an integer count is a strong signal.
3. **Running balance** per asset, sorted by time: the first point where it goes negative dates a
   missing inflow.
4. **Bisect** the observed balance (or nonce) between two heights/times to find the exact
   block/day where replay and truth diverge; then read that block/day.
5. **Match the amount**: search fees, rewards, transfers for a record set whose sum equals the delta
   exactly (to the base unit when available).
6. **Sum across compartments** before blaming a compartment: internal transfers cancel at account
   level, so the account-level residual is what missing *external* flows must explain.

### 5. Classify

| Class | Decision test | Typical evidence |
|---|---|---|
| 1. Code bug | The facts are recorded on chain / in the provided exports, the spec covers them, and the unit got them wrong (or dropped/overwrote them). | Your recomputation ≠ unit's; raw observation retained but comparison missing; a known contract not catalogued; wrong timezone |
| 2. Spec error | The code does what the spec says, and the spec's rule produces the wrong verdict on real facts. | Quote the rule; show the real case it mis-handles |
| 3. Missing spec | The spec is silent and the code guessed (or refused). | No rule covers it; name the page where it belongs |
| 4. Owner data | The unit is right given its inputs; an input is missing, short, unscoped or unconfigured. | Export ends before the checkpoint; missing ledger export; key lacks a scope; provider key unset; budget exhausted |
| 5. By design | The spec deliberately makes it unassessable and no source can decide it. | Venue gives no balance for the period; spec rule says `unassessable` |

Tie-breakers:

1. Is the missing fact **obtainable** from what the unit already has or could fetch itself? Yes →
   1 (or 2/3 if the spec forbids/ignores it). Only the owner can supply it → 4.
2. Would a **correct implementation of today's spec** pass? Yes → 1. No → 2 or 3.
3. Tolerance hides failures too: if a `verified` account's slack exceeds typical record sizes, a
   missing record passes unnoticed → spec issue (see hl.md, specs#43).
4. One account can have several causes. Keep attributing until the whole residual is explained or
   you state what remains unexplained.

### 6. Act per class

1. **Code bug** → worktree `git -C ~/workspace/litmus-tax/<repo> worktree add
   ~/workspace/worktrees/<repo>-<branch> -b <branch> origin/main`; read the repo's AGENTS.md and
   `.agents/rules/python.md`; add a **regression test built from the real case** (the retained
   evidence documents, real heights/rows) that fails without the fix; run the repo's checks; open a
   PR saying why (the failing account, the residual, how it was proven) and what the owner sees after
   the fix. Shared/portfolio bugs: same, in that repo, or describe precisely if another agent owns it.
   In a worktree, the shared interpreter still imports the unit from the main checkout (editable
   install): run checks and tests with `PYTHONPATH=$PWD/pkg/src`. `platform/scripts/test_tenancy.py`
   runs `<workspace>/<unit>`, so for the storage suite copy it to `<scratch>/ws/platform/scripts/`,
   symlink `<scratch>/ws/<unit>` to the worktree, and run it from there with `--unit <unit> --full-suite`
   (cex golden books: `LITMUS_TEST_CEX_EXPORTS=~/workspace/litmus-tax/example/data`).
2. **Spec error / missing spec** → issue on `litmus-tax/specs`: page and rule (link at a commit),
   the rule quoted, the real evidence, a proposed rule text, the options and your recommendation.
3. **Owner data** → one precise action per gap: venue/menu, the export's exact title (as the unit's
   guide prints it), account/subaccount, period `from..to` (both dates), where to upload, and what it
   should close (checkpoint, asset, expected amount). For edits, the full edit body plus the evidence
   that justifies it; preview it (`POST …/edits/preview`) if you have write access.
4. **By design** → cite the rule, confirm the code matches it, and say whether a source or rule
   change could make it assessable (issue if yes).

### 7. Verify after the fix

1. The fix must close the residual **exactly** (or within tolerance for a stated reason): predict the
   new `expected` before rerunning.
2. Offline first: run the fixed pure functions over the retained evidence (DB export) and check the
   gap/residual disappears, and nothing else changes.
3. Then (with admin, or by the owner): sync/verify through the API, re-pull `…/verification`, and
   confirm the checkpoint passes and no new item appears. After a narrower rerun, confirm earlier
   observations are still there.

## Report

Per account (numbered list):

1. `account` (unit, resources) — status → failing checkpoints (`at`, compartment, asset, delta).
2. Root cause(s), with the proof (the matching amount, the block/tx/row, the rule).
3. Class (1-5).
4. Action: PR/issue link, or the owner action verbatim, or "by design, Rule X".
5. Expected effect after the action (which checkpoint closes, to what value).
6. Residuals not explained, and why.

End with any playbook change worth folding back into this skill (a new signature, a new source).
