# tribulnation-sdk 2.13.0

Perpetual markets expose the account's leverage, and `available_notional()` has
defaults built on it.

New:

1. `PerpMarket.leverage(*, refetch=False) -> Decimal`: the multiple of free
   collateral this account can open as notional on the market; opening `n` of
   notional takes `n / leverage` of collateral. It is account-specific, like
   `fees()`, so it lives on the market rather than in the public `rules()` or the
   bucket-level `collateral()`. Venues cache it; `refetch=True` reads it again.
   The default raises `NotImplementedError`. Forwarded through `PerpExchange`,
   `TradingVenue`, `TradingMarkets` and the gateway (`LeverageReq`/`LeverageResp`).
2. `available_notional()` defaults: `collateral().free_collateral` for markets, and
   `free_collateral * leverage()` for perpetual markets. Venues may still override it
   with a more precise figure.

Implemented by Aster 0.7.0, dYdX 0.13.0, Hyperliquid 0.13.0 and Lighter 0.6.0, which
require SDK >=2.13.0 and which the SDK extras now require. Other adapters are
unchanged and raise `NotImplementedError` from `leverage()`; Bybit's support
matrix now declares this as partial support. See ADR 0038.

Gateway servers and clients need 2.13.0 on both sides to serve `leverage`; other
requests are unchanged.

Qualification on 2026-10-08: all 14 declared venues have passing, verified
read-suite evidence, and all 13 market venues have passing consistency evidence,
against the unchanged Catalogue pin `1851660ac2bed8243dd9ce9c7297fe05c7130973`.
The existing Bit2Me native-ticker limitation (ADR 0014) remains visible.

All 1,442 repository unit tests pass.
