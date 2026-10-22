# tribulnation-grvt 0.1.0

Requires typed-grvt >=0.2.0 and typed-core >=0.13. Routing through `MarketSDK` and
`ReportSDK` needs the SDK release carrying `accounts.Grvt`; the SDK floor must rise to
it when this package is released.

New:

1. Market: USDT-margined perpetuals; public data, account reads with an API key (a
   read-only one suffices), and trading with its private key (verified on testnet).
   `perp_collateral` reads the cross bucket and, for a market holding an isolated
   position, that position's own bucket (verified on testnet).
2. Report: snapshots of the funding wallet and of each trading sub-account's futures and
   spot wallets; the futures cash includes isolated positions' balances.
