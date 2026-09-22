# Exchange-wide personal history: venue investigation

This audit inspects the repository implementations and the installed typed clients,
and checks the official Bybit transaction-type documentation for funding scope.
It does not claim live API verification. `Exchange.trades_history(None, start, end)`
and `PerpExchange.funding_payments(None, start, end)` select the whole exchange;
a string keeps the existing single-market behavior. Exchange-wide records retain the
native `market_id`, including historical symbols absent from today's catalogue.

An unimplemented SDK mapping is distinguished below from an unavailable upstream
endpoint. Enumerating currently listed markets is not a complete history fallback.
Only Hyperliquid and dYdX implement exchange-wide history in this change. All
other exchanges raise `NotImplementedError` for a `None` market selector, even
where a native endpoint makes a future implementation feasible. Existing
single-market methods remain available according to their existing support.
Every native page must retain the SDK request-level retry boundary.

| Venue | Native history and pagination | Scope and implementation decision |
| --- | --- | --- |
| Hyperliquid | Account fills and funding are already account-wide upstream; their existing market adapters filter the returned coin. Native timestamp paging and retention apply. | Priority implementation: spot and perpetual fills, perpetual funding, retaining native market identity and exchange boundaries. See [fill adapter](../packages/impl/hyperliquid/pkg/src/tribulnation/hyperliquid/market/impl/trades.py) and [funding adapter](../packages/impl/hyperliquid/pkg/src/tribulnation/hyperliquid/market/impl/funding.py). |
| dYdX | Indexer subaccount fills and funding endpoints can omit the market filter. | Priority implementation: account-configured subaccount scope; perpetual fills and funding. See [fill adapter](../packages/impl/dydx/pkg/src/tribulnation/dydx/market/impl/trades.py) and [funding adapter](../packages/impl/dydx/pkg/src/tribulnation/dydx/market/impl/funding.py). |
| Bybit | `trade.trade_history(category, symbol=None)` uses cursor pages in seven-day windows. `account.transaction_log(category='linear', type='SETTLEMENT')` is account-wide and has the same paging shape. | Deferred: spot fills and linear perpetual funding are feasible follow-ups; both exchange-wide methods currently raise `NotImplementedError`. Perpetual fills additionally require scope work: the linear category also contains dated futures, and execution rows lack a contract-type discriminator. Filtering against today's perpetual catalogue would lose delisted fills. |
| Bit2Me | `v1.trading.trades.list(symbol=None)` supports all spot fills with offset/total pagination, maximum 50 rows. | Feasible follow-up; exchange-wide mapping not implemented. Spot-only exchange, so no perpetual funding. Existing [market adapter](../packages/impl/bit2me/pkg/src/tribulnation/bit2me/market/impl/trades.py) already has offset paging and a reusable parser. |
| Bitget | UTA `trade.order.fills_paged(product)` already returns all symbols; Classic mix fills accept optional symbol and product type. Classic spot fills require symbol in the installed typed client. ID cursors operate within 90-day windows. | Feasible UTA spot and perpetual/mix follow-up; not implemented. Classic spot cannot simply remove the symbol argument. Funding remains intentionally unsupported: Classic and UTA ledger discriminator values are open-ended, so the existing implementation refuses to guess funding types. See [fills](../packages/impl/bitget/pkg/src/tribulnation/bitget/market/impl/history.py) and [funding rationale](../packages/impl/bitget/pkg/src/tribulnation/bitget/market/perp_market.py). |
| Coinbase | Advanced Trade `orders.historical.fills_paged(product_ids=None)` provides native account-wide cursor pages. | Feasible follow-up; not implemented. Must partition spot/perpetual products and obtain the correct quote asset for fees without silently dropping delisted products. INTX perpetual funding ledger is unavailable through the current client surface; CFM dated-futures `funding_pnl` is not a substitute. See [fills](../packages/impl/coinbase/pkg/src/tribulnation/coinbase/market/impl/trades.py) and [funding rationale](../packages/impl/coinbase/pkg/src/tribulnation/coinbase/market/perp_market.py). |
| Kraken | Spot `account.trades_history(pair=None)` provides account-wide offset/count pages, at most 100 rows. Whole-second exclusive start needs adjustment and local filtering. | Feasible spot follow-up; not implemented. Mapping historical pair names to SDK IDs and quote assets needs care. Kraken Futures Market currently supports public data only; private fills and funding stay unsupported. See [spot adapter](../packages/impl/kraken/pkg/src/tribulnation/kraken/market/impl/trades.py) and [Futures exclusions](../packages/impl/kraken/pkg/src/tribulnation/kraken/market/perp_market.py). |
| Binance | Spot `account.my_trades` and USD-M `trading.user_trades` require symbol. USD-M `account.income_paged(symbol=None, income_type='FUNDING_FEE')` supports native account-wide funding, page-number pagination, and retained recent history. | Exchange-wide fills unsupported; a current-market scan is incomplete. Futures private Market methods already raise a futures permission error, so native funding remains a follow-up rather than bypassing that policy. Spot Market currently reads at most 1,000 fills per 24-hour window; this task does not broaden that existing pagination. See [spot adapter](../packages/impl/binance/pkg/src/tribulnation/binance/market/spot_market.py) and [Futures exclusions](../packages/impl/binance/pkg/src/tribulnation/binance/market/perp_market.py). |
| MEXC | Spot `account.trades` requires symbol, limits each response to 100 records, and the current adapter performs one request. Futures `trade.order_deals_paged` also requires symbol; `account.funding_records_paged(symbol=None)` can fetch account-wide funding with numbered pages. | Exchange-wide fills unsupported. Native funding is feasible upstream but not implemented; existing perpetual Market private methods intentionally remain unsupported. See [spot adapter](../packages/impl/mexc/pkg/src/tribulnation/mexc/market/impl/trades.py) and [perpetual exclusions](../packages/impl/mexc/pkg/src/tribulnation/mexc/market/perp_market.py). |
| KuCoin | Private futures funding history requires symbol and supports offset/max-count paging with bounded time windows. Typed spot/futures clients contain private fill endpoints, but the current Market implementations expose public data only. | Exchange-wide methods remain unsupported; extending private Market support needs separate mapping and qualification. Spot account reporting already exists separately. See [Market exclusions](../packages/impl/kucoin/pkg/src/tribulnation/kucoin/market/markets.py). |
| Deribit | `trading.get_user_trades_by_currency` can retrieve fills by currency and kind with trade-ID boundaries. `account.get_transaction_log_paged` is currency-scoped and uses continuation cursors. | Potential future currency sweeps require precise exchange partitioning and funding-ledger mapping. Current Market implementation deliberately exposes public data only; both private methods remain unsupported. See [Market exclusions](../packages/impl/deribit/pkg/src/tribulnation/deribit/market/markets.py). |
| Ethereum | This package provides EVM report snapshots/history through RPC and explorer providers, not a Market/Exchange surface. | Not applicable. On-chain transaction legs are not personal exchange fills or perpetual funding payments. See [declared support](../packages/impl/ethereum/impl.toml). |

Typed-client evidence lives under `.venv/lib/python3.12/site-packages/typed_<venue>/`
in the inspected environment. The endpoint names above identify the concrete local
sources; no raw HTTP workaround, dependency patch, or live account request was used.
Native availability alone does not establish SDK completeness or live qualification.

Bybit's [transaction-type definitions](https://bybit-exchange.github.io/docs/v5/enum#typeuta-translog)
identify `SETTLEMENT` as perpetual funding/session settlement and use `DELIVERY` for
USDC futures delivery. The [transaction-log fields](https://bybit-exchange.github.io/docs/v5/account/transaction-log)
separate perpetual funding from USDC session P&L: a future adapter should map
`funding`, never `cashFlow`. This investigation does not add an exchange-wide
Bybit implementation.
