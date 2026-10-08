# tribulnation-sdk 2.15.0

Adds `OrderRejected`, so a strategy can tell a definitive order refusal from an
ambiguous failure. See ADR 0043.

New:

1. `tribulnation.sdk.OrderRejected` (also in `tribulnation.sdk.core`), a subclass
   of `ApiError`: the venue answered that the order was not accepted, so nothing
   rests and nothing filled, and re-sending is safe. Ambiguous failures (network
   errors, timeouts, 5xx and other answers that do not establish the order's fate)
   are never `OrderRejected`; they keep their current classes.
2. Venues raise it only where their answer makes the refusal certain; it is opt-in
   per venue, so its absence proves nothing. This release: Hyperliquid 0.15.0, Aster
   0.9.0 and Lighter 0.8.0. dYdX and the other venues are unchanged.
3. The gateway codec encodes `OrderRejected`, so a `ProxySDK` client receives the
   same class.
4. `place_order` docstrings (`Market`, `TradingMarkets`, `Exchange`,
   `TradingVenue`) document it under `Raises:`, alongside the ambiguous `ApiError`
   and `NetworkError`.

Existing `except ApiError` handlers still catch it. A `ProxySDK` client older than
its gateway decodes `OrderRejected` as a plain `Exception`, which `except ApiError`
no longer catches: upgrade clients with or before gateways.

This release requires Aster 0.9.0, Hyperliquid 0.15.0 and Lighter 0.8.0, which
require SDK >=2.15.0; the SDK extras now require those versions. Upgrade the SDK and
those adapters together. Other adapters are unaffected.

The live market suite now also qualifies the read-only account methods (fees, open
orders, trade and funding history, positions, collateral, leverage, available
notional) on each venue's recorded account, and read reports (payload version 5)
record the account mode (ADR 0042). This is a live qualification change: every
declared venue was requalified (ADR 0033).

`OrderRejected` is verified by unit fixtures only; no live trading run covers it.

Qualification on 2026-10-08: all 14 declared venues have passing, verified
read-suite evidence (payload version 5, including the account reads), and all 13
market venues have passing consistency evidence, against the unchanged Catalogue pin
`1851660ac2bed8243dd9ce9c7297fe05c7130973`. The existing Bit2Me native-ticker
limitation (ADR 0014), Bitget's venue-wide withdrawal suspension (ADR 0027) and the
Binance USD-M and MEXC spot `fees` waivers (ADR 0042) remain visible.

All 1,603 repository unit tests pass.
