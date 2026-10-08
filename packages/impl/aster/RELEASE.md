# tribulnation-aster 0.7.0

Requires SDK >=2.13.0. New perpetual `leverage()`: the symbol's configured initial
leverage, from its `positionRisk` rows (one per side in hedge mode; the lower is
used should they differ). A missing row raises `MissingData`. Cached per symbol;
`refetch=True` reads it again.

Perpetual `available_notional()`, previously unsupported, is now the SDK default:
the cross bucket's `availableBalance` times `leverage()`. Like `collateral()`, it
raises `NotImplementedError` for isolated positions, and it ignores the leverage
bracket's notional cap.

Upgrade the SDK and this adapter together.
