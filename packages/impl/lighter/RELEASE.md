# tribulnation-lighter 0.6.0

Requires SDK >=2.13.0. New perpetual `leverage()`: `1 / initial margin fraction`,
the account's configured fraction for the market, or the market default for a market
never configured (or configured with a zero fraction, which previously failed).
Cached per market; `refetch=True` re-reads the account.

Perpetual `available_notional()` is unchanged (free cross collateral × leverage),
now built on `leverage()`; it stays an override because isolated positions are
funded from cross collateral. Spot `available_notional()` is unchanged, now
provided by the SDK default.

Upgrade the SDK and this adapter together.
