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
| [0008](0008-bitget-classic-and-uta-coin.md) | Coexisting Classic and UTA Bitget coin perpetuals | Accepted; UTA support deferred by 0010 |
| [0009](0009-catalogue-owned-asset-identity.md) | Catalogue-owned instrument asset identity | Accepted |
| [0010](0010-defer-bitget-uta-coin.md) | Defer Bitget UTA coin support | Accepted |
| [0011](0011-liquidity-independent-consistency.md) | Compare available quote sides without guaranteeing liquidity | Accepted |
| [0012](0012-deribit-public-mainnet-private-testnet.md) | Deribit mainnet public metadata and testnet private Report evidence | Accepted |
| [0013](0013-all-read-suites-release-gate.md) | Require all supported read-only suites alongside market consistency | Accepted; amends 0003 and 0006 |
| [0014](0014-bit2me-native-ticker-limitation.md) | Preserve Bit2Me native tickers with a visible upstream quote limitation | Accepted; amends 0003 and 0011 |
| [0015](0015-single-venue-doc-examples.md) | Linear per-venue documentation examples without hidden support | Accepted |
