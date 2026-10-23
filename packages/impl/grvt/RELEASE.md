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

Release qualification on 2026-10-22 used the read-only mainnet API key (`token` mode,
ADR 0047) and passed the read suites and market consistency. Committed evidence under
`release-evidence/grvt/` matches pinned Catalogue
`e3ad9fbd6cd49fb84855c3d3fccbe9f1936a13f1`; offline release verification passes. This
adapter release follows SDK 2.20.0 publication.
