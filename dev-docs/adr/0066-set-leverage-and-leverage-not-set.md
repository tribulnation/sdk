# ADR 0066: `set_leverage` and `LeverageNotSet`

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: proposed; implemented for Aster, Bybit, Extended, GRVT, Hyperliquid, Lighter,
   margin.trade and RISEx, not release-verified; Kraken Futures and Nado refuse
   (`NotImplementedError`, before any request)
2. Date: 2026-11-18

## Context

Bitget's unified account lists a symbol's leverage only once the account has set one,
so `leverage()` refuses rather than guess the venue's default (ADR 0064). On
2026-11-17 a live hedge on `bitget:usdt:MORPHOUSDT` failed on every step for that
reason: nobody had set the leverage by hand, and the SDK offered no way to set it. The
refusal arrived as a plain `ValueError`, which callers could not tell apart from
other bad values.

The engine wants a market it has never traded to be configured without a person
setting leverage in the venue's app. The decision of when and to what is the
caller's; the SDK only needs to report the missing setting distinctly and to provide
the call that sets it.

## Decision

1. `LeverageNotSet` (`tribulnation.sdk`, `tribulnation.sdk.core`) is raised by
   `leverage()` when the account has no leverage set on the market and the venue
   applies none by default. It subclasses `Error` and `ValueError`, so code catching
   the earlier `ValueError` keeps working. Bitget raises it; venues that always
   report a setting (their default for unconfigured markets) never do.
2. `MarginMarket.set_leverage(leverage)` sets the account's leverage on one market,
   with root delegations on `TradingMarkets`, `PerpExchange` and `TradingVenue`. The
   value is checked before any request, raising `ValueError`: venues that take whole
   multiples refuse fractions (`whole_leverage`), others accept the venue's own step,
   and a value the venue's unit cannot carry exactly is refused rather than rounded.
   It never changes a margin mode: cross where the SDK trades
   cross, isolated only where the account's setting already is isolated or the venue
   allows nothing else. After setting, shared leverage reads are dropped, so the next
   `leverage()` asks the venue. Each venue logs the change at `INFO` on its module's
   logger (`<market id>: leverage set to <value>`); the caller's logging configuration
   decides where it goes.
3. The SDK never calls `set_leverage` on its own, and `leverage()` keeps refusing when
   nothing is set. Applying a default is the caller's policy.
4. Venues:
   1. Aster: `POST /fapi/v1/leverage`, whole, under the symbol's leverage lock shared
      with the `-2027` check (ADR 0055); the margin type is left alone.
   2. Bitget: `POST /api/v3/account/set-leverage`, whole, `USDT-FUTURES`, `crossed`, on
      UTA accounts only; it lands with Bitget's perpetual trading, the only venue that
      raises `LeverageNotSet`.
   3. Bybit: `POST /v5/position/set-leverage`, buy equal to sell, on the instrument's
      `leverageStep`; "leverage not modified" (110043) counts as done. The margin mode
      is account-wide and untouched. Bybit gains `leverage()` with it.
   4. Extended: `PATCH /user/leverage`, decimal; the venue is cross only.
   5. GRVT: the signed `set_position_config`, with the instrument's current margin type
      read afresh and sent back; up to 6 decimals, within the instrument's range.
   6. Hyperliquid and margin.trade: `updateLeverage`, whole, cross unless the account's
      setting is isolated or the asset is isolated-only.
   7. Lighter: the `L2UpdateLeverage` transaction with the position's margin mode (cross
      without one), through the orders' nonce path but not their batch. The fraction is
      10000 / leverage and must be whole, so 3x is refused, not sent as 3.0003x. An
      accepted transaction can still be refused by the sequencer afterwards.
   8. RISEx: the signed `update_leverage` permit, whole, at most 255 (a `uint8`) and
      checked locally against the market's `max_leverage` before signing (above it the
      permit reverts on chain); the margin mode is a separate setting.
   9. Refusing, with `NotImplementedError` before any request: Kraken Futures (cross
      leverage is the margin schedule's; a leverage preference moves the market to
      isolated margin) and Nado (cross margin has no setting). dYdX's `MsgUpdateLeverage` is not
      wrapped by the typed client yet. Binance, KuCoin and MEXC can set leverage but the
      SDK does not trade their perpetuals; Deribit has no per-market setting.
5. The gateway carries both: a `set_leverage` request (`market_id`, `leverage`) with an
   empty `set_leverage` reply, and `LeverageNotSet` as a typed remote exception.

## Contract

`docs/contract/market.yml` lists `set_leverage` as a perpetual-only method. Venues
that cannot set leverage (dYdX, Nado) declare explicit `partial` method lists instead
of `support = "full"`.

## Alternatives considered

1. Have `leverage()` fall back to a default on Bitget: it would report a number the
   venue never confirmed, and could under-hold (ADR 0064).
2. Have the SDK set a default before a market's first order: the same objection as
   ADR 0055 raised against setting leverage unasked; the choice belongs to callers.
3. Let callers use the typed clients directly: it would not cross the gateway, which
   is how the engine reaches venues.
