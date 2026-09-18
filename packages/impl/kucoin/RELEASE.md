# KuCoin 0.3.0 release candidate

Requires SDK >=2.1.0 and typed-kucoin >=0.3.0. Adds credential-free public
Market for Classic spot and linear perpetuals: native discovery/tickers/rules,
REST depth (1–100 levels), shared five-level streams, six candle intervals,
perpetual index/funding/statistics. Private Wallet/Earn/Report scope is unchanged.
Inverse and dated contracts, account fees and private Market methods remain
unsupported. See dev-docs/kucoin-public-market.md for bounds, units and sparse history.

Exact-version surfaces and consistency evidence was captured on 2026-09-18
against merged Catalogue main (including PR #137). The KuCoin release gate passes
against that data. Publish SDK 2.1.0 before merging this release PR.
Reverify evidence against the final merged inputs; evidence expires after seven days.
Terminal rollout requires its own lock, replay and deployment review.
