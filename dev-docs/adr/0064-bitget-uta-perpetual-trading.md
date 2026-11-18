# ADR 0064: Bitget trades USDT-margined perpetuals on a Unified Trading Account

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: proposed; implemented, not release-verified; builds on
   [ADR 0060](0060-bitget-qualifies-uta.md) and [ADR 0043](0043-order-rejected.md)
2. Date: 2026-11-17

## Context

Before this change, `tribulnation-bitget` was read-only, and its trading methods raised
`NotImplementedError`. The prop engine trades Bitget USDT-M perpetuals on the tracked
Unified Trading Account (UTA). That is the same account Bitget qualifies with under
ADR 0060.

Bitget runs two account modes with separate APIs. A UTA uses `/api/v3/` and one
multi-asset margin pool. A Classic account uses `/api/v2/` and keeps a separate wallet
for each product line. Bitget's placement answers only the order ID. A modified order's
`qty` is its total size, so it includes any part already filled. The UTA pool reports
`effEquity`, the haircut equity of the whole pool, which still counts the initial
margin (`imr`) of open positions. The futures `books` channel carries `seq`/`pseq` but
no checksum.

ADR 0043 lets each venue decide which of its answers prove that an order was refused.

## Decision

1. **Scope.** Trading is implemented only on a UTA account's `usdt` exchange, on cross
   margin in one-way position mode. This covers `place_order`, `cancel_order`,
   `cancel_open_orders` and `replace_order`, plus `query_order` through `order-info`.
   - On a Classic account, on `spot` and on `usdc`, trading raises `NotImplementedError`.
     The adapter does not place an order whose margin bucket it would have to guess.
   - Bitget itself refuses orders from an account in hedge mode, because it requires a
     `posSide`.
   - This matches ADR 0060, under which the UTA account qualifies and Classic is
     unobserved.
2. **Order types.**
   - `LIMIT` is sent `gtc`, or with `settings['bitget']['time_in_force']` (`ioc` or
     `fok`).
   - `POST_ONLY` is `post_only`.
   - `MARKET` is an `ioc` limit at the order's price, which bounds it.
   - `settings['bitget']` is `BitgetSettings` in `Market.Settings`.
   - An immediate order is read back once through `order-info`. `filled_qty` is its final
     fill when the order is already done, and `None` otherwise.
3. **Definitive refusals (ADR 0043).** `place_order` raises `OrderRejected` in two cases.
   - The request is malformed (`BadRequest`).
   - Bitget answers one of these codes, each of which leaves nothing placed:
     - `22002`: no position to reduce.
     - `40762`: size over the balance.
     - `43012`: insufficient balance.
     - `45110`: under the minimum order value.

   Any other venue error stays an ambiguous `ApiError`. Auth, rate-limit and network
   errors keep their classes.
4. **Order not found (ADR 0059).** Bitget answers `25204` for an order it does not know.
   That code was confirmed live, as were `40768` and `43001` on Classic v2.
   - `cancel_order` raises `OrderNotFound`.
   - `query_order` returns `None`.
   - `cancel_open_orders` with nothing open returns an empty result.
5. **Replace.** An order is modified in place with `autoCancel` only when three things
   hold: nothing of it is filled, and its side and time in force are unchanged. Any
   other order is cancelled and the replacement placed anew.
6. **Free collateral (behaviour change).** On UTA, `perp_collateral().free_collateral` is
   `max(effEquity - imr, 0)`, no longer `effEquity`. `available_notional` follows,
   because it multiplies free collateral by the contract's maximum leverage. `margin_mode`
   is `cross` unless every settings row for the symbol is `isolated`.
7. **Leverage and collateral ID.**
   - `leverage()` is the symbol's cross row of `account.settings`. It raises `ValueError`
     until a cross leverage is set for the symbol, rather than guessing the venue
     default.
   - `collateral_id()` is the unified pool `<account>:usdt`.
8. **Qualification declarations.** `impl.toml` declares the trading methods together with
   `leverage` and `collateral_id`.
   - Under ADR 0042, a declared `leverage` or `collateral_id` becomes a required account
     read on every margin reference market.
   - `usdc` has no account reads, so it lists both under
     `[qualification.market.unsupported]`, next to its other reads.
   - On `usdt` both are required, so the UTA qualification account needs a cross
     leverage set for the reference market (`BTCUSDT`).
9. **Futures book stream.** On futures, `depth_stream` fails with `NetworkError` when the
   `seq`/`pseq` chain breaks.

## Alternatives considered

1. **Trading on Classic as well.** Classic needs a second order path, with its own margin
   coins and product-line wallets, and no account remains to verify it (ADR 0060).
2. **Treating every 4XX as `OrderRejected`.** Bitget uses 4XX for more than refusals,
   including codes whose meaning is undocumented. A wrong refusal tells the caller that a
   resting order is dead.
3. **Keeping `free_collateral = effEquity`.** That counts margin already in use as free,
   so the reported opening capacity overstates what the venue accepts.
4. **Defaulting `leverage()` to the venue default when no row exists.** Bitget does not
   publish that default for each account and symbol, so the value would be a guess.

## Consequences

1. Bitget needs fresh `bitget_uta` surfaces and consistency evidence (ADR 0033).
   - The read suite now also requires `leverage` and `collateral_id` on
     `usdt:BTCUSDT`.
   - The evidence covers reads only. Trading is verified by unit tests against an
     in-memory signed UTA venue, and by the live mainnet run of 2026-11-16, which
     confirmed `25204`.
2. Consumers that read UTA `free_collateral` or `available_notional` see lower values
   while positions are open.
3. Recovering the private fills stream after a Bitget service upgrade (`30033`) or a lost
   login (`30004`) depends on `typed-bitget>=0.6.1`.
