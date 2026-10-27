# tribulnation-sdk 3.0.0

A breaking release. Markets split by what they trade: spot markets read balances,
margin markets read positions and collateral, and every market names the money its
orders spend with a collateral ID. Account and snapshot reads take a caller-chosen
`ttl`, and concurrent readers of one account share one venue request. Every market
adapter must be upgraded with it; see the end of these notes.

Breaking changes:

1. **Spot and margin market types** ([ADR 0051](../../dev-docs/adr/0051-spot-perp-market-types-collateral-ids.md)).
   `Market` keeps books, trades, orders, rules and fees and loses `position()`,
   `collateral()` and `available_notional()`. It splits into `SpotMarket` and
   `MarginMarket`; `PerpMarket` now derives from `MarginMarket`. Exchanges split the
   same way into `SpotExchange` and `PerpExchange`; only `PerpExchange` has an
   exchange-wide `collateral()`. The spot stand-ins are removed outright, without
   deprecation shims:

   | 2.x | 3.0 |
   | --- | --- |
   | `market.position()` on spot (total base, order holds included) | `market.balances().base` (`total`, and `free` without holds) |
   | `market.collateral()` on spot (the quote balance) | `market.balances().quote` |
   | `market.available_notional()` on spot (buys only) | `balances()`: `quote.free` for buys, `base.free` for sells |
   | `sdk.collateral('<account>:<exchange>:<market>')` | `sdk.perp_collateral(<market id>)`, or the market's `collateral()` |
   | `sdk.collateral('<account>:spot')` (raised) | `sdk.collateral('<account>:spot:<asset>')` |
   | `isinstance(market, PerpMarket)` | `is_perp(market)`, `is_spot(market)`, `is_margin(market)`, or `market.kind` |

   The full migration guide is in [Collateral](../../docs/market/collateral.md#migrating-from-2x).
2. **`leverage(refetch=...)` is replaced by `ttl`** ([ADR 0054](../../dev-docs/adr/0054-caller-chosen-read-staleness.md)).
   `refetch=True` becomes `ttl=None`, which is the default. Leverage is no longer
   cached forever: a call without `ttl` asks the venue each time (Lighter, Hyperliquid,
   Aster, Extended, GRVT, margin.trade). Pass a `ttl` to reuse a recent answer.
   `rules(refetch=...)` and `fees(refetch=...)` are unchanged.
3. **Gateway protocol `tribulnation-gateway.v2`.** Spot requests change meaning
   (`position`, `available_notional`, `collateral` and `collateral_id` address margin
   markets only; spot markets answer `balances`; spot `rules` replies carry `base` and
   `quote`), and `leverage` takes `ttl` instead of `refetch`. A 3.0 gateway refuses v1
   clients, including peers that name no subprotocol (SDK 2.17 and earlier); a 3.0
   client refuses a v1 gateway. Upgrade a gateway and all of its clients together.
4. **Adapter floors.** Market adapters subclass the changed base classes, so each
   adapter release that goes with this one requires `tribulnation-sdk>=3.0.0`, and the
   SDK's venue extras require those releases. Older adapters do not work with 3.0.

New:

1. `SpotMarket.balances()` returns `SpotBalances(base, quote)`, each a
   `Balance(total, free)`, where `free` excludes what open orders hold.
   `SpotMarket.rules()` returns `SpotRules`, whose `base` and `quote` are the venue's
   own asset IDs. `SpotExchange.balance(asset)` reads one asset.
2. Collateral IDs: `SpotMarket.collateral_ids()` (base and quote) and
   `MarginMarket.collateral_id()`, the money that funds new orders on a market. IDs
   are opaque strings led by the account key: `<account>:<spot exchange>:<asset>` for
   a spot asset, `<account>:<perp exchange>` for a margin pool. Markets that spend the
   same money return the same ID: on a unified account (Hyperliquid, unified Lighter) a
   perpetual returns its collateral token's spot ID. `sdk.collateral(id)` resolves any
   collateral ID to `Collateral(equity, free_collateral)`. Venues that do not map it
   raise `NotImplementedError`.
3. `is_spot`, `is_perp` and `is_margin` narrow a market or exchange for the type
   checker, and every market and exchange has `kind: Literal['spot', 'perp']`.
4. Caller-chosen read staleness ([ADR 0054](../../dev-docs/adr/0054-caller-chosen-read-staleness.md)).
   `balances`, `balance`, `position`, `perp_position`, `collateral`,
   `perp_collateral`, `leverage`, `available_notional`, `next_funding`, `tickers` and
   `perp_stats` take `ttl: timedelta | None = None` on markets, exchanges, venues and
   `TradingMarkets`:
   1. `ttl=None` (the default) asks afresh: the answer comes from a request started
      after the call. No stored answer is used and no request in flight is joined.
   2. A `timedelta`, `timedelta(0)` included, shares: an answer whose request started
      less than `ttl` ago is reused, else a request in flight is joined, else one is
      started. Callers with different `ttl`s share one key.
   3. Venues without shared reads accept `ttl` and ignore it.
5. Shared account reads ([ADR 0053](../../dev-docs/adr/0053-shared-account-reads-aster-max-leverage.md)).
   `tribulnation.sdk.core.SharedReads` shares one request between concurrent callers
   and keeps successful answers for callers that pass a `ttl`; failures are not kept,
   and a caller's cancellation never cancels the shared request. Lighter (`/account`
   and the market stats snapshots), Hyperliquid (`clearinghouseState` per dex,
   `spotClearinghouseState`) and Aster (all-symbol `positionRisk` and the futures
   account) answer every market of an account with one request, so a burst of readers
   with a `ttl` sends one.
6. The gateway carries `ttl` on each of those requests (an ISO 8601 duration; absent
   or null is `None`). Shared answers live in the gateway process, so every task
   reading through one gateway shares them.

Behaviour changes in the adapters released with this version (see each package's
notes):

1. Aster lowers a symbol's leverage setting to the maximum it now allows only when an
   order is refused for being above it (`-2027`), and resends that order once; it never
   raises a setting ([ADR 0055](../../dev-docs/adr/0055-aster-lower-leverage-on-refusal.md),
   amending ADR 0053).
2. Binance, Bit2Me, Bitget, Bybit, Coinbase, Kraken and MEXC spot markets no longer
   serve `position`, `collateral` and `available_notional` through the SDK interface,
   and do not map `balances` yet. Aster, Hyperliquid, Lighter and margin.trade spot
   markets serve `balances` and collateral IDs; dYdX, Extended, GRVT and the perpetuals of
   Aster, Hyperliquid, Lighter and margin.trade serve `collateral_id()`.

This release goes with tribulnation-aster 0.13.0, -binance 0.9.0, -bit2me 0.10.0,
-bitget 0.12.0, -bybit 0.8.0, -coinbase 0.6.0, -deribit 0.7.0, -dydx 0.20.0,
-extended 0.2.0, -grvt 0.2.0, -hyperliquid 0.19.0, -kraken 0.8.0, -kucoin 0.7.0,
-lighter 0.12.0, -margin-trade 0.2.0 and -mexc 3.0.0, which require SDK >=3.0.0.
tribulnation-ethereum is unchanged: it implements Report only.
