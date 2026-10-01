# tribulnation-hyperliquid 0.10.1 release candidate

Fix order payloads rejected by Hyperliquid when rounded quantities or prices
serialize in exponent form, or quantities retain fractional trailing zeros.

- Order sizes now serialize as positional decimals without trailing zeros.
- Prices of 10000 or more also serialize in positional form after rounding.
- Regression fixtures check the typed client's pre-signing payload for normalized
  quantities, trailing zeros, and a six-figure price.

Requires tribulnation-sdk >=2.7.0 and typed-hyperliquid >=2.3.0.

No live trading round trip is recorded; release qualification uses read-only suites.
