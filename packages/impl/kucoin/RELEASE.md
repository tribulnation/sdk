# tribulnation-kucoin 0.9.0

Requires SDK >=4.2.0 and typed-kucoin >=0.6.2 (was typed-kucoin >=0.5.1).

Added:

1. Unified Trading Account (UTA) support for spot and linear perpetuals (#408). `KucoinMarket.new(..., mode='classic'|'unified')`, or leave `mode` unset to detect the account mode once per client (`GET /api/ua/v2/account/mode`) on the first account read or trade. `accounts.Kucoin.mode` passes it through from tribulnation-sdk 4.4.0. Public market data and `rules()` are the same in both modes; the SDK never switches the account mode.
2. In unified mode every account read, order and fill goes through UTA REST V2 and the UTA private WebSocket (`execution` channel). Orders are acknowledged before matching on both lines: a `MARKET` order is read back once (done with nothing filled raises `OrderRejected`) and a crossing `POST_ONLY` is cancelled after the acknowledgement. `place_orders` places one by one (no batch placement); `cancel_orders` and `cancel_open_orders` use the native batch and per-symbol cancels.
3. UTA margin: `perp_collateral` is the one unified pool in USD (collateral-adjusted equity, available margin, account IM/MM); `collateral_id` is `<account>:perp` for USDT- and USDC-settled contracts alike. Spot `balances` read the unified per-currency assets.
4. UTA fills: `trades_stream` reports the fee and liquidity role; `trades_history` walks seven-day windows (trades, liquidations, ADL); `funding_payments` 90-day windows.
5. UTA error codes map like the Classic ones; an endpoint answering that the account is not unified raises `ApiError`, never `OrderRejected`.
6. `scripts/live_trading.py` gains `--mode` and `--fill`.

Changed:

1. typed-kucoin floor 0.6.2: the UTA clients, plus nullable `subTradeType`, `stopPrice`, `remark` and `endAt` on futures trades and orders.

Verified live on a mainnet UTA on 2026-11-28 (`live_trading.py --mode unified`): mode detection (`unified`), the unified pool, spot balances and the perpetual account reads; on perpetual `XBTUSDTM` a post-only place, query, `open_orders` and cancel, a second cancel raising `OrderNotFound`, a crossing post-only cancelled unfilled, and a minimum-size market buy and sell filled, seen on `trades_stream` (taker, fee in USDT) and in `trades_history`, flat afterwards. UTA spot orders and fills, and Classic orders and fills, are unit-tested against fake responses only.

Every Classic method is unchanged.

Release qualification on 2026-11-28 passed the read suites (account reads on a private UTA account, mode detected) and market consistency.
Committed evidence under `release-evidence/kucoin/` matches pinned Catalogue
`e3ad9fbd6cd49fb84855c3d3fccbe9f1936a13f1`; offline release verification passes.
