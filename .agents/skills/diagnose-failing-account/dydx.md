<!-- vendored from workspace/.agents/skills/diagnose-failing-account/dydx.md — do not edit; run `python scripts/sync.py agents` -->
# dydx: diagnosing a failing dYdX account

Repo `litmus-tax/dydx`, DB `litmus_dydx`. Spec: `specs/docs/policies/03-unit-contract/units/dydx/index.md`
(Rule 13 verification, 13.2 unscanned bank ranges; Rule 14 equity is never a checkpoint;
subpages `verification.md`, `decoding.md`, `bridges.md`).

## Where the audit lives

1. **Served audit** `GET /v1/dydx/resources/{r}/verification`. Checkpoints per
   `(subaccount:<n>|bank|staking|vault, dydx:asset:<…>)` at block heights, tolerance `0`.
   `detail`: `heights` (checkpoint time → height), `verified_heights`, `failed_heights`,
   `divergences`, `fetched`, `predicates`, `creation_height`, `history_complete`.
2. **Items** `GET /v1/dydx/resources/{r}/items`: unknown event/message types, uncatalogued
   perpetual/denom/asset, unnamed block-level payer, missing correlation key, non-netting internal legs.
3. **Jobs** `GET /v1/dydx/jobs?resource={r}`: which sync/verification ran, with which options
   (`no_bank`, `offline`, `height`).
4. **DB fallback** (`litmus_dydx`):
   1. `source.verifications(address, height, ok, report, at)`: retained comparison per height;
      `report.subaccounts[n].{replayed, chain}` (USDC quantums, positions); `report.compartments.bank`
      only if bank was compared.
   2. `source.state_evidence(height, data.path, data.response_base64)`: raw gRPC answers
      (`Query/Subaccount`, `Query/AllBalances`, indexer `perpetualMarkets`).
   3. `source.syncs(report)` (`fetched`, `verified_heights`), `source.coverage`, `public.litmus_jobs`.

```sql
-- overwritten comparisons: a later, shorter report at the same height
SELECT height, ok, at, length(report::text) FROM source.verifications ORDER BY height;
-- raw bank observations (decode: base64 -d | strings); Noble USDC denom ibc/8E27…45B5, 6 decimals
SELECT height, data->>'response_base64' FROM source.state_evidence
WHERE data->>'path' LIKE '%AllBalances' ORDER BY height;
```

## Signatures

| Signature | Cause | Class | Action |
|---|---|---|---|
| `observed: null` (or interval `unassessable`) on `bank` but `AllBalances` is retained at that height | A narrower rerun (`no_bank`/`offline`) **overwrote** the retained comparison (dydx#28) | 1 | PR; owner re-verifies that height online with bank on |
| Mismatch on subaccount USDC or positions | Missing record or decoding bug | 1 | Bisect (`first_divergence` / `litmus-dydx debug bisect`), scan that block, inspect events; decoder/catalogue PR |
| Bank, staking or vault mismatch in an unscanned range | By spec `unassessable` (Rule 13.2) | 5 (specs#44 to make it decidable) | Bisect `AllBalances` across heights to localise it anyway |
| Uncatalogued perpetual/denom/asset item; legs unscaled | Catalogue gap | 1 | Catalogue PR with the real event |
| Unnamed block-level payer item | Module account not in catalogue | 1 or 3 | Identify the module account |
| Equity/PnL differs from the indexer | Not a checkpoint (Rule 14) | none | Do not chase |
| Portfolio: a dYdX `bridge` out (`dydx → noble`, IBC) left unmatched beside an evm CCTP claim (`noble → base/ethereum`) of about the same amount, a minute later | Two-hop route. Since evm#41, CCTP claims carry `src_network_id: noble`, and portfolio `bridges.compatible_bridges` compares source with source, so `dydx` ≠ `noble` refuses the pair (13 links lost, 2026-09-28) | 1 (portfolio) | Chain the hops: a withdrawal whose `dst_network` equals the deposit's `src_network` is compatible |

## Ground truth

1. Archive gRPC node: `Query/Subaccount` and `Query/AllBalances` at any height. The unit's verify
   job does exactly this: `POST /v1/dydx/resources/{r}/verification` with body `{"height": [h…]}`
   (admin; bank stays on unless `no_bank`), or a sync with `{"verify_at": [h…]}` (max 100). The job's
   `result` is the new served verification: check `detail.verified_heights` and the interval ending at
   that height (2026-09-29: height 106581881 closed the 2026-09-22→23 bank interval; `passed`).
2. Public indexer `https://indexer.dydx.trade/v4/…`: fills, transfers, historical PnL; **no bank
   balances**, never a checkpoint source.
3. Bisect bank by reading `AllBalances` at a few heights between a passing and a failing checkpoint.

## Costs and limits

1. Archive node reads are cheap per height, but block scans over wide ranges are not: bisect first,
   scan only the divergence block.
2. Before recommending a re-verification, check it keeps bank on and covers every height the
   previous richer report had (hard rule 4).
