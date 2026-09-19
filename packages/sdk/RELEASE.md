# tribulnation-sdk 2.2.0 release candidate

Register Deribit's credential-free public mainnet Market in MarketSDK. The Deribit
extra now requires tribulnation-deribit >=0.3.0, which adds active spot and linear
perpetual data under native exchange IDs `spot` and `perp`.

The supported subset provides discovery, tickers, REST and streaming depth,
1m/5m/15m/1h candles on native instruments, and linear perpetual index/statistics.
Routed spot candles, daily candles, inverse contracts, scheduled funding, rules,
account fees and private Market operations remain unsupported.

Deribit 0.3.0 is already published and requires SDK >=2.2.0. This release
completes the dependency pair and makes the updated Deribit extra installable.

Publication requires fresh all-venue read-suite and applicable Market consistency
evidence against Catalogue main. Deribit private Report qualification uses the
approved testnet exception; private mainnet account behavior remains unverified.
Catalogue mappings and Terminal rollout remain separate work.

SDK 2.2.0 publication also qualifies Bit2Me's existing native ticker limitation
against stable one-sided books (ADR 0022). Three timely, exact-ID discrepancies
remain visible limitations; malformed data, changing book sides, empty books and
other venues' mismatches are not covered. Fresh version-5 consistency reports and
all supported read suites are required; earlier reports cannot be relabeled.

The first SDK 2.2.0 publication attempt was blocked by the older qualification
policy. This candidate retains the unpublished SDK version and records fresh evidence.
