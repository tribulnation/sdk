# tribulnation-dydx 0.13.0

Requires SDK >=2.13.0. New perpetual `leverage()`: `1 / effective initial margin
fraction`, the market's fraction adjusted upward by open-interest caps. dYdX has no
per-account setting, so it is the same for every subaccount, cross or isolated.
`refetch=True` reloads the market list shared with `rules()`.

`available_notional()` is unchanged (subaccount `freeCollateral` × the same
leverage), now provided by the SDK default rather than an override.

Upgrade the SDK and this adapter together.
