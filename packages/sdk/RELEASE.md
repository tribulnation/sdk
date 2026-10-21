# tribulnation-sdk 2.19.0

Adds margin.trade: accounts, Market and Report routing, and the `margin-trade` extra.

New:

1. `accounts.MarginTrade` (`venue = "margin-trade"` or `"margin-trade-testnet"`): the
   master `address` (base58) and the master's or an approved agent's `private_key`,
   defaulting to `$MARGIN_TRADE_ADDRESS`/`$MARGIN_TRADE_PRIVATE_KEY` (or the
   `MARGIN_TRADE_TESTNET_` variables on testnet). With `public = true` the address
   alone serves account reads; a private account requires the key. The variables of
   one network are never used for the other.
2. `MarketSDK` and `ReportSDK` route `margin-trade` and `margin-trade-testnet`
   accounts to `tribulnation-margin-trade` (spot and USDC-margined perpetuals;
   snapshots and history by address). The gateway's account schema accepts both venue
   IDs.
3. The `margin-trade` extra installs `tribulnation-margin-trade>=0.1.0`.

Qualification tooling accepts hyphenated testnet venue IDs (`margin-trade-testnet`),
mapping them onto the mainnet slug.

This release goes with tribulnation-margin-trade 0.1.0, which requires SDK >=2.19.0
and typed-margin-trade >=0.1.1. Other adapters are unaffected.

Qualification on 2026-10-21, against the Catalogue pin
`70d93fa09c351f5a24c915b348e8f38f31c7b6a6` (Catalogue main with the margin.trade
platform; the pin moves from `1851660a`): all 15 venues have passing, verified
read-suite evidence, and every market venue passing consistency evidence.

All 2,149 repository unit tests pass.
