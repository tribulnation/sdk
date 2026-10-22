# tribulnation-sdk 2.20.0

Adds GRVT and Extended: accounts, Market and Report routing, and the `grvt` and
`extended` extras.

New:

1. `accounts.Grvt` (`venue = "grvt"` or `"grvt_testnet"`): an `api_key`, its signer's
   `private_key` and the `trading_account_id`, defaulting to `$GRVT_API_KEY`,
   `$GRVT_PRIVATE_KEY` and `$GRVT_TRADING_ACCOUNT_ID` (or the `GRVT_TESTNET_`
   variables on testnet). The variables of one network are never used for the other.
   An API key alone serves every account read, so a read-only key suffices; its
   private key adds placing orders; with `public = true` and no API key, market data
   only ([ADR 0047](../../dev-docs/adr/0047-grvt-credential-modes.md)).
2. `accounts.Extended` (`venue = "extended"` or `"extended_testnet"`): one sub-account's
   `api_key`, and optionally its `stark_private_key` (with `stark_public_key`) and
   `vault`, defaulting to the `EXTENDED_` variables (or the `EXTENDED_TESTNET_`
   variables on testnet). The variables of one network are never used for the other.
   The API key reads the sub-account and cancels its orders; the Stark key and vault
   add placing orders; with `public = true`, market data only.
3. `MarketSDK` and `ReportSDK` route `grvt`/`grvt_testnet` accounts to
   `tribulnation-grvt` (USDT-margined perpetuals; snapshots of the funding wallet and
   the trading sub-accounts) and `extended`/`extended_testnet` accounts to
   `tribulnation-extended` (USD-collateral perpetuals; snapshots and history of one
   sub-account). The gateway's account schema accepts all four venue IDs.
4. The `grvt` extra installs `tribulnation-grvt>=0.1.0`, and the `extended` extra
   `tribulnation-extended>=0.1.0`.

Qualification tooling:

1. An account id selector selects only that account, never the other accounts of the
   venue it names: `--account grvt` used to collect `grvt_trade` too, and the read
   suites refused to run.
2. Market consistency records Extended's RFQ-market tickers, whose bid and ask are the
   venue's indicative book rather than the quotes `depth` returns, as a visible
   limitation ([ADR 0048](../../dev-docs/adr/0048-extended-rfq-indicative-tickers.md)).

This release goes with tribulnation-grvt 0.1.0 and tribulnation-extended 0.1.0, which
require SDK >=2.20.0. Other adapters are unaffected.
