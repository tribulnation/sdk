# Architecture Decision Records

[Developer documentation](../README.md)

ADRs preserve the reasoning behind public contracts, architecture, guarantees,
policy, and significant tradeoffs in the SDK and its development tools. They are
not a changelog or a substitute for API documentation and tests.

## Recording a decision

1. Copy [0000-template.md](0000-template.md), use the next four-digit number and a
   descriptive filename, and add a row to the index below.
2. Record the context, decision, alternatives, and consequences. Use `proposed`
   while a decision needs approval, and `accepted` once agreed. Acceptance does
   not assert that implementation, live verification, or release is complete.
3. Preserve accepted decisions and their rationale. A changed decision gets a new
   ADR; update the old record's status and the index with the superseding or
   amending link. Editorial corrections may clarify, but must not change the decision.
4. Link relevant records from implementation PRs and contributor documentation.
   Keep credentials, account records, and private operational details out of ADRs.

## Index

| Number | Decision | Status |
| --- | --- | --- |
| [0001](0001-public-rules-and-account-fees.md) | Separate public market rules from quoted account base fees | Superseded by 0002 |
| [0002](0002-combined-side-specific-fees.md) | Combined maker/taker and buy/sell rates, without optional payment discounts | Accepted |
| [0003](0003-local-consistency-release-evidence.md) | Local consistency checks and offline release evidence | Accepted; amended by 0004, 0006, 0009 |
| [0004](0004-empty-book-consistency-coverage.md) | Empty books without invented price coverage | Amended by 0011 |
| [0005](0005-bitget-product-identities.md) | Explicit Bitget futures product identities | Accepted; amended by 0008 |
| [0006](0006-release-evidence-scope.md) | Separate exact coverage and add non-market release evidence | Accepted; amended by 0009 |
| [0007](0007-dydx-quote-asset.md) | dYdX quote and fee assets are USDC | Accepted; quote field removed by 0009 |
| [0008](0008-bitget-classic-and-uta-coin.md) | Coexisting Classic and UTA Bitget coin perpetuals | Accepted; UTA support deferred by 0010; Classic retired by 0018 |
| [0009](0009-catalogue-owned-asset-identity.md) | Catalogue-owned instrument asset identity | Accepted |
| [0010](0010-defer-bitget-uta-coin.md) | Defer Bitget UTA coin support | Accepted; amended by 0018 |
| [0011](0011-liquidity-independent-consistency.md) | Compare available quote sides without guaranteeing liquidity | Accepted |
| [0012](0012-deribit-public-mainnet-private-testnet.md) | Deribit mainnet public metadata and testnet private Report evidence | Accepted |
| [0013](0013-all-read-suites-release-gate.md) | Require all supported read-only suites alongside market consistency | Accepted; amends 0003 and 0006; amended by 0016 |
| [0014](0014-bit2me-native-ticker-limitation.md) | Preserve Bit2Me native tickers with a visible upstream quote limitation | Accepted; amends 0003 and 0011; amended by 0022 |
| [0015](0015-single-venue-doc-examples.md) | Linear per-venue documentation examples without hidden support | Accepted |
| [0016](0016-report-snapshot-release-scope.md) | Qualify Report snapshots; application auditing owns history correctness | Accepted; amends 0013 |
| [0017](0017-venue-resource-policies.md) | Venue-owned resource policies without whole-lifecycle middleware | Accepted |
| [0018](0018-retire-bitget-classic-coin.md) | Retire confirmed Bitget Classic coin markets while preserving historical IDs | Accepted; amends 0008 and 0010 |
| [0019](0019-kucoin-public-market.md) | KuCoin public spot and linear perpetual data with native identities and base units | Accepted |
| [0020](0020-kraken-public-perpetuals.md) | Kraken public linear perpetual data with native identities and hourly funding settlement conversion | Accepted |
| [0021](0021-deribit-public-market.md) | Deribit public spot and linear perpetuals with explicit candle and funding limits | Accepted |
| [0022](0022-bit2me-one-sided-ticker-limitation.md) | Extend the Bit2Me native ticker limitation to stable one-sided books | Accepted; amends 0014 |
| [0023](0023-ticker-quote-volume.md) | Native 24-hour quote volume in tickers | Accepted |
| [0024](0024-exchange-account-history.md) | Native exchange-wide personal history with market-attributed records | Accepted |
