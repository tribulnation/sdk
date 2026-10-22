# tribulnation-grvt 0.1.0

Requires SDK >=2.20.0 (the release carrying `accounts.Grvt` and the `grvt`
Market/Report routing), typed-grvt >=0.2.0 and typed-core >=0.13.

New:

1. Market: USDT-margined perpetuals; public data, account reads with an API key (a
   read-only one suffices), and trading with its private key (verified on testnet).
   `perp_collateral` reads the cross bucket and, for a market holding an isolated
   position, that position's own bucket (verified on testnet).
2. Report: snapshots of the funding wallet and of each trading sub-account's futures and
   spot wallets; the futures cash includes isolated positions' balances.

Release qualification uses the read-only mainnet API key (`token` mode, ADR 0047); the
evidence is under `release-evidence/grvt/`. This adapter release follows SDK 2.20.0
publication.
