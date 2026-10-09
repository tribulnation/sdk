# tribulnation-bybit 0.7.0

Requires SDK >=2.16.0 and typed-bybit >=0.3.1. `trades_stream` accepts the new
keyword-only `settings` argument of SDK 2.16 (ADR 0044) and ignores it: Bybit
has no trades-stream options. Fills and every other method are unchanged.

The SDK floor rises to 2.16.0, whose `Market.trades_stream` declares `settings`.
Upgrade the SDK and this adapter together.

The support matrix now lists Bybit Market as partial: account `leverage()` was
never implemented and still raises `NotImplementedError`. Metadata only; no code
change.
