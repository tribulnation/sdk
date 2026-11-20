# tribulnation-evedex 0.1.0

The first release: EVEDEX perpetuals (evedex.com) as an SDK Market venue and Report.
Requires SDK >=4.1.0 and typed-evedex >=0.1.0;
SDK 4.2.1 adds the `Evedex` account to `MarketSDK` and `ReportSDK` and the `evedex` extra.

1. `EvedexMarket`: one exchange, `perp`, keyed by instrument name (`BTCUSD`). Public data
   needs no credentials: discovery, tickers, rules, depth and a shared book stream,
   candles, index, `perp_stats` and the next hourly funding settlement.
2. With an API key (a read-only token): fees, order queries, open orders, trade history,
   positions, collateral, leverage, available notional and remaining position limit;
   with the wallet's private key also `LIMIT` and `MARKET` (IOC limit) orders,
   cancellations, `set_leverage` and the fills stream. `POST_ONLY`, `funding_rates` and
   `funding_payments` are not supported (see `impl.toml`).
3. `Report` snapshots one account's trading balance, positions and wallet with an API key.

Release qualification on 2026-11-20 passed the read suites and market consistency on a
public account only, by policy ([ADR 0072](../../../dev-docs/adr/0072-public-only-release-qualification.md)):
account reads and Report are NOT verified by release evidence; they were verified by
hand on mainnet on 2026-11-19. Committed evidence under `release-evidence/evedex/`
matches pinned Catalogue `e3ad9fbd6cd49fb84855c3d3fccbe9f1936a13f1`; offline release
verification passes.
