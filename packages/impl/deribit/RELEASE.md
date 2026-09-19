# tribulnation-deribit 0.3.0 release candidate

Add credential-free public mainnet Market data for active spot and linear perpetual
instruments. Exchange IDs are `spot` and `perp`; symbols retain Deribit's native
spelling, including `BTC_USDT` and `BTC_USDC-PERPETUAL`.

- Discovery and selected/bulk tickers preserve native identifiers and unknown values.
- REST depth supports 1–100 levels; shared public streams support 1–20 levels.
- Native spot and linear perpetual candles support 1m, 5m, 15m and 1h, with bounded
  pagination and aware, half-open time bounds. Routed spot candles are unsupported.
- Perpetual statistics expose the native index, mark and optional base open interest.

Inverse contracts, dated futures, options, combinations, daily/4h candles, rules,
account fees, scheduled funding and private Market operations remain unsupported.
Native WebSocket candle requests validate; the observed HTTP candle endpoint does
not. Broad option summaries have a recorded typed-client defect; supported product
scopes validate without bypasses. See the public Market qualification handoff.

Requires tribulnation-sdk >=2.2.0 and typed-deribit >=0.3.0. Publish after SDK 2.2.0.

Release qualification records Market and Wallet/Earn metadata on mainnet,
private Report snapshots on testnet under ADR 0012, and Market consistency.
The 2026-09-19 candidate passes 29 read-suite cases and 23 consistency checks
against Catalogue main `720d17275eeb025bad0e2da1f43f674531471dab`.
Private mainnet account behavior remains unverified. Report history correctness and
completeness are outside snapshot qualification. Catalogue market mappings and
Terminal deployment remain separate work.
