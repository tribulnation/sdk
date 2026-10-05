# tribulnation-aster 0.4.2 release candidate

Fix Aster order quantities and prices serialized in exponent notation after SDK
step/tick rounding. Spot and perpetual MARKET, LIMIT and POST_ONLY requests now
preserve positional integer quantities such as 190 and limit prices such as 120,
with fractional trailing zeros removed.

Regression tests exercise the typed-client serialization and query encoding for
both venues and all supported order kinds. Market orders still ignore SDK price;
LIMIT uses GTC and POST_ONLY uses GTX.

Known upstream limitation: typed-aster 0.2.0 still serializes Decimal values below
1E-6 in exponent notation. This patch does not fix that range; see
`typed-client-issues.md`. Live release qualification covers read-only Market and
Report surfaces and market consistency, not order placement.

Requires tribulnation-sdk >=2.8.0 and typed-aster >=0.2.0.
