# tribulnation-kucoin 0.8.0

Requires SDK >=4.2.0 and typed-kucoin >=0.5.1 (was SDK >=3.0.0, typed-kucoin >=0.4.1).

Added:

1. Account and trading support on Classic spot (HF orders, the `trade` account) and USDT/USDC-settled linear perpetuals (one-way, cross margin), exchange IDs `spot` and `perp` (#405). `accounts.Kucoin` takes `api_key`/`api_secret`/`api_passphrase` (defaults `$KUCOIN_API_KEY`/`$KUCOIN_API_SECRET`/`$KUCOIN_API_PASSPHRASE`); `public=True` stays credential-free for market data.
2. Orders: `place_order(s)`, `cancel_order(s)`, `cancel_open_orders`, `replace_order(s)` (cancel then place), `query_order`, `open_orders`. `LIMIT` is GTC, `POST_ONLY` sets `postOnly`, `MARKET` is an IOC limit at the SDK price. Orders are checked against `rules()` before sending and never rounded; futures quantities convert between contracts and base units. `client_order_id` is sent as `clientOid` ([ADR 0029](../../../dev-docs/adr/0029-client-order-ids.md)).
3. Account reads: spot `balances`/`collateral_ids`/`collateral`; perpetual `perp_position`, `perp_collateral`, `collateral_id`, `leverage`/`set_leverage`, `available_notional`, `funding_payments`; `fees` with the account's actual rates (maker rebates negative) plus any reported tax rate.
4. Fills: `trades_stream` over the private order channels, `trades_history` in seven-day windows.
5. Errors: definitive KuCoin codes raise `OrderRejected` (`PositionLimitExceeded` for `126042`), missing orders `OrderNotFound` on cancel and `None` on query ([ADR 0043](../../../dev-docs/adr/0043-order-rejected.md), [ADR 0059](../../../dev-docs/adr/0059-replace-orders-and-order-not-found.md)). `tribulnation.kucoin.retry_after` reads KuCoin's quota reset from `RateLimited`.

Fixed:

1. Spot `query_order` of an unknown or expired order ID returns `None`. KuCoin answers it with `data: null`, which raised `ValidationError` (#406).

Verified live on a mainnet account on 2026-11-27 with a key without trading permission: fees, balances, open orders, trades history, position, cross collateral, leverage, available notional and `collateral_id`; `trades_stream` connects on both lines; `query_order` of an unknown ID is `None` on both lines. Order placement, cancels, `set_leverage` and fills are unit-tested against fake responses only and not yet verified live.

Every other method is unchanged.

Release qualification on 2026-11-27 passed the read suites (account reads on a private account) and market consistency.
Committed evidence under `release-evidence/kucoin/` matches pinned Catalogue
`e3ad9fbd6cd49fb84855c3d3fccbe9f1936a13f1`; offline release verification passes.
