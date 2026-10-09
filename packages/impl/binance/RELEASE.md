# tribulnation-binance 0.7.0

Requires SDK >=2.16.0 and typed-binance >=1.2.0. `trades_stream` accepts the new
keyword-only `settings` argument of SDK 2.16 (ADR 0044) and ignores it: Binance
has no trades-stream options. Fills and every other method are unchanged.

The SDK floor rises to 2.16.0, whose `Market.trades_stream` declares `settings`.
Upgrade the SDK and this adapter together.
