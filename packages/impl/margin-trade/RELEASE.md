# tribulnation-margin-trade 0.1.0

Requires SDK >=2.19.0 (the release carrying `accounts.MarginTrade` and the
`margin-trade` Market/Report routing) and typed-margin-trade >=0.1.1 (10 s WebSocket
pings: the venue drops a connection about 30 s after the last ping).

New:

1. Market: spot (`PEARL/USDC`) and USDC-margined perpetuals, public data, account reads
   by address, and trading with the master's or an approved agent's key (verified on
   testnet).
2. Report: perp and spot wallet snapshots; history of fills, funding and transfers.

The venue renamed its token from `PRL` to `PEARL` (spot pair and perpetual). Depth
streams (perpetual and spot, mainnet) and the fill stream (testnet) stayed open for
75 s on typed-margin-trade 0.1.1.

Release qualification on 2026-10-21 passed the read suites and market consistency.
Committed evidence under `release-evidence/margin-trade/` matches pinned Catalogue
`70d93fa09c351f5a24c915b348e8f38f31c7b6a6`; offline release verification passes.
This adapter release follows SDK 2.19.0 publication.
