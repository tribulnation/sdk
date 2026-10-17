<!-- vendored from workspace/.agents/skills/diagnose-failing-account/cex.md — do not edit; run `python scripts/sync.py agents` -->
# cex: diagnosing a failing exchange account

Repo `litmus-tax/cex`, DB `litmus_cex`. Spec: `specs/docs/policies/03-unit-contract/units/cex/`
(`verification.md` checkpoints, zero openings, hints; `records.md` Rule 12 unattributed moves;
`opaque.md` copy-trading and strategy wallets; `edits.md`; `venue-specs.md`).

## Where the audit lives

1. **Served audit** `GET /v1/cex/resources/{r}/verification`. Checkpoints per `(compartment, asset)`
   (compartments like `spot`, `futures`, `earn:*`, `futures:copytrade`, `unattributed`). An empty
   `evidence` list = a manual snapshot (JSON file or `snapshot` edit): read its provenance first.
   `detail`: `opening_balance` (zero before the first record), `tolerance_rule`,
   `unassessable[{reason, node_ids, subaccount}]`, `hints` (`quiet_period` > 31 days without records,
   including last record → last checkpoint since cex#61), `rollups`, `pricing_usage`.
2. **Items** `GET /v1/cex/resources/{r}/items`: `cex.verification_failed` (with
   `explained by {observation_type: sum}`), `cex.missing_subaccount_attribution`,
   `cex.opaque_result_unresolved`, `cex.snapshot_fetch_failed`, `cex.historical_price_gap`,
   `cex.unconfirmed_match` (confirm with the item's `resolve.request_template`), `cex.override_spec`
   and `cex.override_redundant` (info, from `add_spec` overrides).
3. **Inputs**: `GET /v1/cex/resources/{r}/coverage` (which exports cover which periods),
   `GET /v1/cex/venues` (guides), `…/records?kind=cex.internal_transfer&compartment=…`,
   `…/evidence/{digest}`.
4. **DB fallback** (`litmus_cex`):

```sql
SELECT r.name, e.path, e.digest, e.size FROM state.evidence e JOIN litmus_resources r USING (resource_id)
WHERE retired_version IS NULL AND path LIKE 'book/evidence/blobs/%' ORDER BY 1, 2;
SELECT r.name, e.kind, e.status, e.request FROM litmus_edits e JOIN litmus_resources r USING (resource_id);
SELECT r.name, s.kind, count(*) FROM state.records s JOIN litmus_resources r USING (resource_id) GROUP BY 1, 2;
-- legs of transfers into candidate compartments
SELECT s.time, l->>'compartment', l->>'amount', s.body->'evidence'->0->>'locator', s.body->'detail'->'attribution'
FROM state.records s JOIN litmus_resources r USING (resource_id), jsonb_array_elements(s.body->'legs') l
WHERE r.name = :'res' AND s.kind = 'cex.internal_transfer'
  AND l->>'compartment' IN ('futures:copytrade', 'spot:strategy', 'futures:strategy', 'unattributed')
ORDER BY 1;
```

   Evidence objects (local stack): small ones inline in MinIO,
   `docker exec litmus-local-minio-1 cat /data/litmus-cex/tenant/<t>/sha256/<digest>/xl.meta | strings | grep '^{'`.
   API captures are `litmus.cex.snapshot.v1` envelopes with base64 bodies; snapshot provenance and
   failed captures (category, endpoint, HTTP status) are in `book/snapshot-attempt.json`.

## Steps specific to cex

1. **Inventory inputs vs the guide.** List uploaded exports (digests; identical digests = identical
   files, often header-only templates). Compare with the venue guide
   `cex/pkg/src/litmus/cex/guides/<venue>.yaml`; for each export **not** uploaded, read its parser in
   `cex/catalogue/<venue>.yaml`: its `Transaction Type`/`Fund Type` enum tells exactly which flows it
   would add.
2. **Rebuild the ledger** per asset from the raw files (csv/openpyxl script): deposits, withdrawals
   (check whether the amount includes the fee), trade legs (base ± size, quote ∓ total, fee in its
   asset), futures P&L and fees. Compare with `expected`.
3. **Running minimum** per asset: the first negative point dates a missing inflow (opening balance,
   reward, transfer in). No negative anywhere → older history is not *required* by the data.
4. **Account-level residual** (sum over compartments) = what missing *external* flows must explain.

## Signatures

| Signature | Cause | Class | Action |
|---|---|---|---|
| Residual ≈ n × a periodic reward; last record well before the checkpoint; `quiet_period` hint to the end | Exports end before the snapshot (bit2me: 57 daily staking rewards after the export end) | 4 | Newer export through the snapshot date |
| Compartment explained only by trades (no `internal_transfer`), negative balance | That compartment's ledger export is missing (mexc `futures_capital_flow`) | 4 | The guide's ledger export for that compartment and period |
| Residuals in airdrop / dust-conversion assets (small, odd assets) | Missing statement export (mexc Spot Statement: Hold and Earn airdrops, MX conversion) | 4 | That export |
| Running balance negative from the first record | Opening balance: older history missing | 4 | Exports from account creation to the first file's start |
| All checkpoints pass, status `unassessable`, `detail.unassessable[].reason = missing_subaccount_attribution` | Half-attributed transfers (bitget spot ↔ copy-trading) | 4 (edit) | `patch_observation` per item, counterpart proved from other exports |
| Opaque compartment result large/implausible, `detail.unresolved` | Its inflow sits in `unattributed` | 4 (edit) | Same patches; recheck the result becomes small |
| Unit `expected` ≠ your recomputation | Parser or spec bug | 1 (or 2) | PR with a test from the real row |
| Trade/transfer times off by whole hours vs chain or klines | Wrong `tz` in the venue spec (mexc spot trades are UTC, cex#60) | 1 | Catalogue PR |
| `cex.snapshot_fetch_failed`, capture `permission_denied` on one endpoint | Key lacks a read scope | 4 | Owner adds the scope (endpoint in `snapshot-attempt.json`) |
| No new checkpoint after a fetching sync; `snapshot-attempt.json` still old; `…/credentials` `configured: false` | No stored credentials: capture is skipped silently (`not_configured`) | 4 | `PUT …/credentials` from the owner's env (with admin), then a fetching sync |
| Upload `unrecognised: Its columns match no known <venue> export` | The venue changed the export layout (Bit2Me 2026-09: `Fee estimated EUR` replaced three EUR columns) | 1 | `add_spec` override now, catalogue PR for the fingerprint (see Evidence by API) |
| Upload `unrecognised: … its values do not validate` | New enum values (Bitget 2026-08: crypto-loan rows, margin `borrow`, one-way futures `buy_deal`) | 1 | Same; list the values with `validate_candidate` (below) |
| Residual of ~0.5 quantum per row on an asset with a `cex.historical_price_gap` | The export truncates each row to the snapshot quantum; without a price the tolerance is the quantum alone (verification Rule 1.4) | 2 (specs#54) | None on the book; don't edit it away |
| Small regular snapshot moves in a check **after** the last record (`explained by no records`), e.g. bitget spot USDT +0.0000202–0.0000217 per hour; the item still says "older exports missing" | Activity after the exports end: Bitget pays Simple Earn flexible interest into **spot** hourly at hh:14 UTC (`Interest` rows of *Spot transactions*); the earn balance stays flat. The capture's `uTime` per coin (`/api/v2/spot/account/assets`) is the last balance change | 4, but dust | Normally absorbed by the value tolerance (next row). To close it exactly: *Spot transactions* from the last export's end through the capture day |
| Tolerance = snapshot quantum only (bitget API strings have 16 decimals → `1E-16`) and a `cex.historical_price_gap` on every recent checkpoint; `book/prices.json` rows `terminal_absent` with `fetched_at` on the checkpoint's own day | A same-day Terminal absence (the close of a UTC day exists only after it ends) was retained for good, so no capture was ever priced (fixed by cex#72: absences retried until read 2 days after the day began) | 1 | After cex#72: a **fetching** sync on a later day (`no_fetch` requests no prices) |
| Position sign opposite to the venue's, P&L right | Venue wording read as trade side (MEXC `buy short` **opens** a short, `sell short` closes it; cex#63) | 1 | Catalogue PR |
| Account closed, no balance source | Genuinely limited | 5 | Terminal zero snapshot only with evidence the account is empty |

Checks run between consecutive snapshot points (verification Rule 1): `expected` = the previous
snapshot + the legs since, so a failed check dates its cause inside that interval only. A day that
"passed" with no new checkpoint can be vacuous: read the sync job's `result.snapshot.status`
(2026-09-30: `failed`, `rate_limited` 429 on `/api/v2/account/bot-assets`, so no capture and no new
check). Read `book/prices.json` with `…/evidence/{digest}` (digest from the DB query above) to see
each checkpoint day's price row (`source`, `fetched_at`).

## Ground truth

1. **Timezone of a file**: take a withdrawal with a tx hash; read its block time from a public RPC
   (`eth_getTransactionByHash`, `eth_getBlockByNumber`). Venue time ≈ block time → UTC; else the offset.
2. **Trade times**: sample ~25 fills; check each price against the venue's public hourly klines at
   offsets 0, +1, +2 h (MEXC `api.mexc.com/api/v3/klines?symbol=&interval=60m&startTime=&endTime=`;
   1m history expires in months). The right offset contains every price; a wrong one misses about a third.
3. **Cross-venue pairs**: a withdrawal on A with the same amount and tx hash as a deposit on B pins
   both files' timezones and proves both sides.
4. **Balances**: decode the API capture (pools, lock periods, `updatedAt`). An `updatedAt` after the
   last record proves activity after the exports end.

## Proving a transfer counterpart (for `patch_observation`)

1. `cex.missing_subaccount_attribution` gives observation id, amount, time and the missing side.
2. Pair each out-without-counterpart with the next return from a candidate compartment of about the
   same amount (copy-trading returns = amount ± profit share), using the query above.
3. Check that the candidate's opaque result, recomputed with the patches, is small and plausible.
4. Edit per item (preview first with `POST /v1/cex/resources/{r}/edits/preview`):
   `{"kind": "patch_observation", "observation": "<id>", "upsert": {"dst_account": "<label>"}, "reason": "<evidence>"}`
   (`src_account` when the missing side is the source).

## Evidence by API (admin grant)

1. **Upload**: `POST /v1/cex/resources/{r}/uploads`, multipart, one `files` part per file (the part's
   base name is kept; Bitget names contain `/`, so pass the base name). Read each `detection`:
   `recognised` (parser, export, rows, period), `duplicate` (same bytes already attached: nothing to
   do), `unrecognised` (reason). The `parser` form field only re-runs detection with that parser.
2. **Attach**: one `add_evidence` edit per recognised file,
   `{"kind": "add_evidence", "digest": "<sha256>", "name": "<file name>", "supersedes": "<evidence id>", "confirm": true}`.
   1. `supersedes` takes the old file's evidence **id**, not its digest. Read the ids from
      `book/evidence/index.json`: its digest comes from the DB query above, its body from
      `…/evidence/{digest}`. Supersede only when the new file is a row-level superset of the old one
      (compare row multisets; Bitget's Earn exports differ between two downloads of the same period,
      so keep both and let policy 01 cex Rule 1 dedupe them across exports).
   2. Don't supersede a header-only entry: identical files collapse to one entry shared by several names.
   3. `confirm: true` only when the file is matched by discriminator or file name and you checked the
      choice; open `cex.unconfirmed_match` items carry the exact body in `resolve.request_template`.
   4. `add_evidence` has no preview. Stage every edit, put `?apply=true` on the last one, then run a
      separate fetching sync for the capture.
3. **Export layout changed / new values**: find why locally with the shared interpreter:
   `litmus.cex.parsing.load.load(path)` gives `fingerprint` and `df`;
   `Catalogue.load('<cex>/catalogue').candidates(fp, venue=…)` and
   `selection.validate_candidate(df, c)` give the refused values. Then do both:
   1. **now**, an `add_spec` override (venue specs Rule 10): the versioned spec copied, renamed (names
      must not collide) and fixed (new fingerprint, enum values, CEL), with any new compartment
      labels under `subaccounts.definitions`. Preview it (`{"add": {"kind": "add_spec", …}}`): the
      preview shows whether it changes records of files already attached. The override wins its
      fingerprint for that resource (`cex.override_spec` items). Only fields the **deployed** schema
      knows are accepted.
   2. **for everyone**, the same change as a catalogue PR with a test from the real rows. After the
      release, `cex.override_redundant` says the override can be withdrawn.
      Withdraw it with a preview first (`{"withdraw": "<edit id>"}`: expect no record or
      status change). Files that were chosen by the override now go back to discriminator or file
      name matching and raise `cex.unconfirmed_match`: confirm them from `resolve.request_template`.
   3. Until cex#62 is deployed, `add_evidence.parser` refuses parser names with spaces or
      parentheses (52 of 108), so an override is also the way to force a parser.

## Third-party balance records (trackers)

1. **Prove accuracy first**, on accounts the unit verifies (see SKILL.md step 2). The 2025-12 tracker
   matched the verified bitget replay on 160/160 asset-instants and on-chain `balanceOf` to the base
   unit.
2. **Localise the residual per asset**: `record(t) − Σ transparent compartments(t)`. What each shape
   means:
   1. constant: an event before the first record;
   2. a step between two records: one missing event in that window (MEXC: two credits of exactly
      30.0000 USDT on 2025-12-29, likely futures bonuses);
   3. a drift: fit the venue's public funding history against the position (MEXC
      `contract.mexc.com/api/v1/contract/funding_rate/history?symbol=&page_num=`, 100 per page from
      today backwards; EUR_USDT funds every 4 h). A fit to 0.0001 also proves the position's sign.
   4. an asset that drops to 0 at once: a points or bonus expiry (MXPOINT, 2025-12-31).
3. **What the book may take**: nothing yet. The spec admits snapshots from exports, API captures,
   JSON files and `snapshot` edits typed from a statement, and is silent on third-party records and
   on an "explained residual" end state (specs#53). Report the attribution; don't load the snapshots.

## Owner actions

Name the venue menu, the export title exactly as the guide prints it, the account/subaccount, the
period `from..to`, the upload route (`POST /v1/cex/resources/{r}/uploads`, then `add_evidence`, or
the app), what the file adds and which checkpoint it should close with the expected amount. If the
account is closed, say whether the export is still downloadable.
