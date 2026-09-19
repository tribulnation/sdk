# tribulnation-sdk 2.2.0 release candidate

Register Deribit's credential-free public mainnet Market in MarketSDK. The Deribit
extra now requires tribulnation-deribit >=0.3.0, which adds active spot and linear
perpetual data under native exchange IDs `spot` and `perp`.

The supported subset provides discovery, tickers, REST and streaming depth,
1m/5m/15m/1h candles on native instruments, and linear perpetual index/statistics.
Routed spot candles, daily candles, inverse contracts, scheduled funding, rules,
account fees and private Market operations remain unsupported.

Publish core first, then Deribit 0.3.0. The extra becomes installable once the
implementation is published; consumers should adopt the pair together.

Publication requires fresh all-venue read-suite and applicable Market consistency
evidence against Catalogue main. Deribit private Report qualification uses the
approved testnet exception; private mainnet account behavior remains unverified.
Catalogue mappings and Terminal rollout remain separate work.
