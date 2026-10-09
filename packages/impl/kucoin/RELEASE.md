# tribulnation-kucoin 0.6.0

Requires SDK >=2.16.0 and typed-kucoin >=0.4.1. `trades_stream` accepts the new
keyword-only `settings` argument of SDK 2.16 (ADR 0044) and ignores it: KuCoin
has no trades-stream options. Fills and every other method are unchanged.

The SDK floor rises to 2.16.0, whose `Market.trades_stream` declares `settings`.
Upgrade the SDK and this adapter together.
