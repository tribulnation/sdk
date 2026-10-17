<!-- vendored from workspace/.agents/skills/diagnose-failing-account/hl.md — do not edit; run `python scripts/sync.py agents` -->
# hl: diagnosing a failing Hyperliquid account

Repo `litmus-tax/hl`, DB `litmus_hl`. Spec: `specs/docs/policies/03-unit-contract/units/hl/`
(`verification.md`, `sources.md` api vs S3 archive, `records.md`, `accounts.md`).

## Where the audit lives

1. **Served audit** `GET /v1/hl/resources/{r}/verification`. Checkpoints exist **only at sync times**
   (snapshots), per `(main|<dex>|spot|staking…, hyperliquid:asset:<id>)`. Tolerance: settlement cash
   `0.01 + Σ|size| × ½ unit of entryPx`, positions `0`, other tokens `1e-9`.
   `detail`: `attestation` (`fills.{complete, chain_breaks, near_retention_cap, twap,
   funded_without_fills, unknown_start_position}`, `funding.{hourly, aggregated, checkable}`,
   `ledger`, `sources`), `interval_residuals`, `history_complete`, `opening`, `snapshots`, `tolerance`.
2. **Items** `GET /v1/hl/resources/{r}/items`: `source_disagreement` (api vs archive), unmapped
   ledger delta types, `hl.gateway_historical_applicability`.
3. **Usage** `GET /v1/hl/usage` (archive budget).
4. **DB fallback** (`litmus_hl`): `source.snapshots(resource_id, time, body)` (`clearinghouseState`
   per dex, `spotState`, staking, `consistent`); `source.evidence(kind, source, body)` raw fills,
   ledger and funding rows (`source` = api or archive); `state.records.body.legs`.

## Signatures

| Signature | Cause | Class | Action |
|---|---|---|---|
| Cash `delta` over tolerance on `main` | Missing funding, fee or ledger row; or api/archive disagreement | 1 or 4 | Check `attestation`, `interval_residuals`, `source_disagreement` items |
| `unassessable`, "bracket is inconsistent" | The snapshot raced a fill (`consistent=false`) | none | Owner re-syncs |
| "history before this checkpoint is not attested complete", `near_retention_cap` or `twap` at cap | Venue retention (10k fills, 2k TWAP) | 4 (or 5 if the archive has nothing) | Owner enables/funds the S3 archive for the early range, or accepts the gap |
| `chain_breaks` / `unknown_start_position` in attestation | Fills history has a hole (position does not chain) | 4 or 1 | Locate the break time; check archive coverage |
| `verified`, but tolerance ≫ typical funding/fee legs | **Vacuous pass**: missing records hidden by slack (hyperliquid2: 1.87 USDC tolerance, 91% of funding legs smaller) | 2 (specs#43) | Spec issue; rebuild observed cash from `positionValue` |
| Unmapped ledger delta type item | Decoder gap | 1 | PR with the real ledger row |

## Checking a `verified` account is really verified

1. Checkpoints compare something: non-zero `expected`/`observed`, positions listed.
2. The first interval (`from: null`) is only as strong as the checkpoint that closes it.
3. **Slack vs record sizes**: a missing record is detected only if its amount > `tolerance − |delta|`.

```sql
WITH legs AS (
  SELECT resource_id, kind, abs((l->>'amount')::numeric) a
  FROM state.records r, jsonb_array_elements(r.body->'legs') l
  WHERE l->>'asset' = 'hyperliquid:asset:0' AND l->>'compartment' = 'main')
SELECT resource_id, kind, count(*), sum((a < :slack)::int) FROM legs GROUP BY 1, 2;
```

4. Alternative cash basis from a snapshot (tight, ~0.002 residual observed):
   unified `spot − Σ sign(szi)·positionValue`; legacy `accountValue − Σ sign(szi)·positionValue`.
5. Positions are exact (tolerance 0): a missing **fill** is always caught; missing **cash-only**
   records (funding, fees, ledger) are the blind spot.

## Ground truth

1. `POST https://api.hyperliquid.xyz/info` with `clearinghouseState` / `spotState` / `userFunding` /
   `userFills` / `userNonFundingLedgerUpdates`: **current state only** for balances; history is
   subject to retention caps.
2. No historical balance source exists: you cannot add checkpoints in the past; you can only
   recompute cash between two existing snapshots from fills + funding + ledger and compare the
   difference with the observed change (`interval_residuals`).
3. S3 archive (requester pays; budget in `/v1/hl/usage`) for fills beyond retention.

## Costs and limits

1. `info` endpoint is rate-limited by weight; page by time windows.
2. Archive reads cost money: estimate from `/v1/hl/usage` before asking the owner to enable it.
