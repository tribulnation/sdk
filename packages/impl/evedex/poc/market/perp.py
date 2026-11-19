# %% [markdown]
# # evedex `market` PoC
#
# Maps `typed_evedex` onto the SDK `market` surface, one method per cell, each executed live. The rules, and how a typed-client issue is reported in `typed-client-issues.md`, are in `.agents/skills/sdk-poc/SKILL.md`.
#
# EVEDEX is a perpetuals exchange with an off-chain order book and on-chain settlement on Arbitrum. Every instrument is a USDT-margined perpetual addressed by its `name` (`BTCUSD`), the id every other call takes. Public data needs no credentials; an API key (`X-API-Key`) serves every REST account read; the wallet's private key signs in (SIWE), signs every order (EIP-712) and opens the private channels.
#
# Everything here runs against **prod** (evedex.com) with the owner's funded account (`EVEDEX_PRIVATE_KEY`, `EVEDEX_API_KEY`), read-only: state-changing cells are written and never run, and the trading lifecycle is a separate script the owner runs (`poc/lifecycle.py`). The demo environment (evedex.io) is not mapped: its instruments are other ids (`BTCUSD:DEMO`) and its trading balance cannot be funded through the API, so it cannot trade.

# %%
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from importlib.metadata import version
from typing_extensions import Any, AsyncGenerator, AsyncIterable, Collection, Literal, Mapping, Sequence, cast
import asyncio
import os

from dotenv import load_dotenv
from typed_evedex import Evedex, BadRequest as EvedexBadRequest
from typed_evedex.core import order_id
from typed_evedex.exchange.fills import AccountFill
from typed_evedex.exchange.market.instruments import InstrumentInfo
from typed_evedex.schemas import Instrument

from tribulnation.sdk.market import Book, Candle, CandleInterval, Fees, FundingPayment, NextFunding, Order, OrderResponse, OrderState, PerpCollateral, PerpPosition, PerpStats, Position, RemainingPositionLimit, Rules, Settings, Ticker, Trade
from tribulnation.sdk.market.exchange import OverflowPolicy

load_dotenv()

stack = AsyncExitStack()
client = await stack.enter_async_context(Evedex.new(
  env='prod',
  private_key=os.environ['EVEDEX_PRIVATE_KEY'],
  api_key=os.environ['EVEDEX_API_KEY'],
))
"""Prod, with the owner's wallet key (orders, private channels) and API key (REST reads)."""

MARKETS = ['BTCUSD', 'ETHUSD', 'XRPUSD']
USDT = 'usdt'
"""The collateral coin, as the venue writes it."""
FUNDING_SETTLEMENT = timedelta(hours=1)

end = datetime.now(timezone.utc)
start = end - timedelta(days=7)


async def instrument_table() -> dict[str, InstrumentInfo]:
  """Every instrument (full records, no metrics), by name."""
  rows = await client.exchange.market.instruments()
  return {r['name']: r for r in cast(list[InstrumentInfo], rows)}


table = await instrument_table()
{
  'typed-evedex': version('typed-evedex'),
  'instruments': len(table),
  'visible': sum(r['visibility'] == 'all' for r in table.values()),
  'trading': {t: sum(r['trading'] == t for r in table.values()) for t in ('all', 'none', 'marketMakerOnly')},
}

# %% [markdown]
# ## Surface
#
# What the client exposes. Widen or narrow the filter until every endpoint the mapping below uses is listed here.

# %%
from sdk_dev.surface import surface

print(surface('typed_evedex', 'Evedex', grep=r'market\.|order_book|candles|fills|orders\.(place_limit|cancel|get|opened|list)|positions\.(list|set_leverage)|account\.(me|available_balance|funding|balance)'))


# %% [markdown]
# ## `markets`
#
# `exchange.market.instruments`: every instrument, delisted ones included (`visibility: none`, `trading: none`: `LDOUSD`, `WIFUSD`, ...). Listed: `visibility == 'all'`. Two of them (`DAX40USD`, `ANTUSD`) are visible but `trading: marketMakerOnly`; `rules().api` says so.

# %%
async def markets() -> Sequence[str]:
  return [name for name, r in (await instrument_table()).items() if r['visibility'] == 'all']


listed = await markets()
(len(listed), listed[:10])


# %% [markdown]
# ## `depth`
#
# `exchange.market.order_book`: aggregated levels, best first, at most 100 per side, stamped with the book time `t`.

# %%
async def depth(market_id: str, /, *, levels: int | None = None, settings: Settings = {}) -> Book:
  raw = await client.exchange.market.order_book(instrument=market_id)
  book = Book(
    bids=[Book.Entry(r['price'], r['quantity']) for r in raw['bids']],
    asks=[Book.Entry(r['price'], r['quantity']) for r in raw['asks']],
    time=raw['t'],
  )
  return book if levels is None else book.limit(levels)


{m: await depth(m, levels=2) for m in MARKETS}


# %% [markdown]
# ## `depth_stream`
#
# `streams.order_book(instrument, round=...)`: every publication is the whole book (100 levels a side), not a delta. `round` is required; `0.1` (the official SDK's default) leaves every instrument at its own tick: XRPUSD's levels are `0.0001` apart and ETHUSD's `0.01`, identical to the REST book. One connection carries every subscription.

# %%
@asynccontextmanager
async def depth_stream(market_id: str, /, *, levels: int | None = None, queue_size: int = 1, overflow: OverflowPolicy = 'latest', settings: Settings = {}) -> AsyncGenerator[AsyncIterable[Book]]:
  async with client.streams.order_book(market_id, round='0.1') as stream:

    async def books():
      async for frame in stream:
        b = frame['orderBook']
        book = Book(
          bids=[Book.Entry(r['price'], r['quantity']) for r in b['bids']],
          asks=[Book.Entry(r['price'], r['quantity']) for r in b['asks']],
          time=b['t'],
        )
        yield book if levels is None else book.limit(levels)

    yield books()


frames: list[Book] = []
async with depth_stream('XRPUSD', levels=2) as stream:
  async for update in stream:
    frames.append(update)
    if len(frames) == 3:
      break
frames


# %% [markdown]
# ## `tickers`
#
# `exchange.market.instruments(fields='metrics')` carries the last price and 24h volumes (`volume` in base units, `volumeBase` in USD: BTC's 8,408 beside 531M on 2026-11-19), but no best bid or ask. Those come from `order_book(marketLevel=1)`, one request per market.

# %%
async def tickers(markets: Collection[str] | None = None, *, settings: Settings = {}, ttl: timedelta | None = None) -> Mapping[str, Ticker]:
  rows = cast(list[Instrument], await client.exchange.market.instruments('metrics'))
  wanted = {r['name']: r for r in rows if r['visibility'] == 'all' and (markets is None or r['name'] in markets)}
  tops = await asyncio.gather(*(client.exchange.market.order_book(instrument=m, market_level='1') for m in wanted))
  return {
    m: Ticker(
      last=r['lastPrice'],
      bid=top['bids'][0]['price'] if top['bids'] else None,
      ask=top['asks'][0]['price'] if top['asks'] else None,
      bid_qty=top['bids'][0]['quantity'] if top['bids'] else None,
      ask_qty=top['asks'][0]['quantity'] if top['asks'] else None,
      base_volume_24h=r['volume'],
      quote_volume_24h=r['volumeBase'],
    )
    for (m, r), top in zip(wanted.items(), tops)
  }


all_tickers = await tickers()
(len(all_tickers), {m: all_tickers[m] for m in MARKETS})


# %% [markdown]
# ## `rules`
#
# `priceIncrement` is the tick, `quantityIncrement` the step; `minQuantity`/`maxQuantity` bound the size and `minVolume` (5 USD everywhere) the notional. `fees` are the instrument's standard rates (0.015% maker, 0.045% taker on all 70, 2026-11-19). `markPriceLimit` (`0.3` on 62 instruments, `0.5` on 8) is the largest distance of a limit price from the mark, so it gives the relative price bounds: the owner's mainnet run (2026-11-19) had a buy 7% under the mark accepted, so the ±5% band the client's docs describe does not hold. `minPrice`/`maxPrice` (the absolute range accepted now, which moves with the price) stay in `details`. `api`: `trading` is `all` (or `schedule`), the session `OPEN` and the matcher `active`.

# %%
async def rules(market_id: str, /, *, refetch: bool = False) -> Rules:
  r = table[market_id]
  return Rules(
    fee_asset=USDT,
    tick_size=r['priceIncrement'],
    step_size=r['quantityIncrement'],
    fixed_min_qty=r['minQuantity'],
    min_value=r['minVolume'],
    max_qty=r['maxQuantity'],
    rel_min_price=1 - r['markPriceLimit'],
    rel_max_price=1 + r['markPriceLimit'],
    fees=Fees.symmetric(maker=r['fees']['maker'], taker=r['fees']['taker']),
    api=r['trading'] in ('all', 'schedule') and r['marketState'] == 'OPEN' and r['matcherState'] == 'active',
    details={'minPrice': r['minPrice'], 'maxPrice': r['maxPrice'], 'maxLeverage': r['maxLeverage']},
  )


{m: await rules(m) for m in [*MARKETS, 'LDOUSD', 'DAX40USD']}


# %% [markdown]
# ## `fees`
#
# `exchange.account.me`: `tradingFees`, "fee rates that apply to the account", with `personalTradingFees` overriding them field by field where set (`null` here).

# %%
async def fees(market_id: str, /, *, refetch: bool = False) -> Fees:
  user = await client.exchange.account.me()
  rates, personal = user['tradingFees'], user['personalTradingFees'] or {}
  return Fees.symmetric(maker=personal.get('makerFee', rates['maker']), taker=personal.get('takerFee', rates['taker']))


{m: await fees(m) for m in MARKETS}


# %% [markdown]
# ## `candles`
#
# `market_data.candles_paged`: rows `[openTime, open, close, high, low, volumeUsd, volume]` (the spec's tuple titles), both bounds inclusive, oldest first within a page; the pager walks backwards from `before`, up to 100,000 rows a page. Every contract interval is a venue `group` of the same name.

# %%
async def candles(market_id: str, /, interval: CandleInterval, start: datetime, end: datetime):
  pages = client.market_data.candles_paged(instrument=market_id, after=start, before=end, group=interval)
  async for page in pages:
    rows = [
      Candle(time=t, open=o, high=h, low=lo, close=c, volume=v, quote_volume=qv)
      for t, o, c, h, lo, qv, v in page
      if start <= t < end
    ]
    if rows:
      yield rows


day = end.replace(minute=0, second=0, microsecond=0) - timedelta(days=1)
{
  m: (len(rows := [c async for page in candles(m, '1h', day, day + timedelta(hours=24)) for c in page]), rows[0], rows[-1])
  for m in MARKETS
}


# %% [markdown]
# ## `query_order`
#
# `exchange.orders.get`: any order, open or closed; an unknown id answers `404 order_not_found_error`. The account's one filled limit order (from the owner's 2026-11-19 capture run) and an unknown id.

# %%
async def query_order(market_id: str, /, id: str) -> OrderState | None:
  try:
    o = await client.exchange.orders.get(id)
  except EvedexBadRequest as e:
    if e.args[1].get('label') == 'order_not_found_error':
      return None
    raise
  if o['instrument'] != market_id:
    return None
  sign = -1 if o['side'] == 'SELL' else 1
  return OrderState(
    id=o['id'],
    price=o['limitPrice'],
    qty=sign * o['quantity'],
    filled_qty=sign * (o['quantity'] - o['unFilledQuantity']),
    active=o['status'] in ('INTENTION', 'NEW', 'PARTIALLY_FILLED'),
  )


KNOWN = '00483:8ea0f9fa29101942ff321425ec'
{
  'filled': await query_order('XRPUSD', KNOWN),
  'other market': await query_order('BTCUSD', KNOWN),
  'unknown': await query_order('XRPUSD', '00483:00000000000000000000000000'),
}


# %% [markdown]
# ## `open_orders`
#
# `exchange.orders.opened`: every open order of the account, all instruments. The account rests nothing now.

# %%
async def open_orders(market_id: str, /) -> Sequence[OrderState]:
  rows = await client.exchange.orders.opened()
  return [
    OrderState(
      id=o['id'],
      price=o['limitPrice'],
      qty=(-1 if o['side'] == 'SELL' else 1) * o['quantity'],
      filled_qty=(-1 if o['side'] == 'SELL' else 1) * (o['quantity'] - o['unFilledQuantity']),
      active=True,
    )
    for o in rows
    if o['instrument'] == market_id
  ]


{m: await open_orders(m) for m in MARKETS}


# %% [markdown]
# ## `trades_history`
#
# `exchange.fills_paged`: the account's fills in `after..before` (`after` exclusive), offset-paged. A fill carries its order id, price, size, maker/taker role and time, but neither side nor fee: the side comes from the orders (`orders.list(id=[...])`, one request per page) and the fee from each order's own fills (`orders.fills`, whose fill ids are the same, one request per order). The order id doubles as the client order id: every order id is chosen by the placing client.

# %%
async def trades_history(market_id: str | None, /, start: datetime, end: datetime) -> AsyncIterable[Sequence[Trade]]:
  async for page in client.exchange.fills_paged(market_id, after=start - timedelta(milliseconds=1), before=end, limit=100):
    fills: list[AccountFill] = [f for f in page if start <= f['createdAt'] <= end]
    if not fills:
      continue
    ids = sorted({f['order'] for f in fills})
    sides: dict[str, Literal['BUY', 'SELL']] = {o['id']: o['side'] for o in await client.exchange.orders.list_paged(id=ids, limit=len(ids))}
    fees: dict[str, Trade.Fee] = {}
    for oid in ids:
      for row in await client.exchange.orders.fills(oid):
        if len(row['fee']) == 1:
          fees[row['id']] = Trade.Fee(amount=row['fee'][0]['quantity'], asset=row['fee'][0]['coin'])
    yield [
      Trade(
        id=f['id'],
        order_id=f['order'],
        client_order_id=f['order'],
        price=f['fillPrice'],
        qty=-f['fillQuantity'] if sides[f['order']] == 'SELL' else f['fillQuantity'],
        time=f['createdAt'],
        maker=f['fillRole'] == 'MAKER',
        fee=fees.get(f['id']),
      )
      for f in fills
    ]


HISTORY_MARKETS: list[str | None] = [None, 'XRPUSD', 'BTCUSD']
{m: [t async for page in trades_history(m, start, end) for t in page] for m in HISTORY_MARKETS}


# %% [markdown]
# ## `trades_stream`
#
# `streams.account.fills` (`orderFills-<exchangeId>`): the account's fills, every instrument, with side and maker flag but no fee (fees arrive on the separate `order-fee` channel). Private channels authorize with the wallet's session: an API key alone is refused before subscribing. Subscribed here for a few seconds; no fills happen without trading.

# %%
@asynccontextmanager
async def trades_stream(market_id: str, /, *, queue_size: int = 1000, overflow: OverflowPolicy = 'fail', settings: Settings = {}) -> AsyncGenerator[AsyncIterable[Trade]]:
  async with client.streams.account.fills() as stream:

    async def trades():
      async for f in stream:
        if f['instrument'] == market_id:
          yield Trade(
            id=f['executionId'],
            order_id=f['orderId'],
            client_order_id=f['orderId'],
            price=f['fillPrice'],
            qty=-f['fillQuantity'] if f['side'] == 'SELL' else f['fillQuantity'],
            time=f['createdAt'],
            maker=f['makerTakerFlag'] == 'MAKER',
          )

    yield trades()


received: list[Trade] = []
try:
  async with asyncio.timeout(5):
    async with trades_stream('XRPUSD') as stream:
      async for update in stream:
        received.append(update)
except TimeoutError:
  pass
{'subscribed': True, 'fills': received}


# %% [markdown]
# ## `place_order`
#
# `exchange.orders.place_limit`, signed with the wallet (EIP-712 `new_limit_order`). `leverage` is part of the signed struct, so every order carries the account's current setting on the instrument (the position record's `leverage`, 1 when never set). `quantity`/`limitPrice` are rounded half-up to 8 decimals before signing, so off-grid values are refused before the call. The order `id` (`DDDDD:<26 hex>`, days since 2025-07-24) is the client's: `client_order_id` is sent as the id, else the client generates one (`typed_evedex.core.order_id`). Mapping: `LIMIT` is GTC (the venue default) and `MARKET` a limit with `timeInForce: 'IOC'` at `price`: the venue's own market order is sized in USD (`cashQuantity`) and bounded only by the instrument's slippage limit, not by `price`. The owner's mainnet run (2026-11-19) confirmed the IOC: a non-crossing one ended `CANCELLED`, nothing resting, and crossing ones filled (a 6.6 XRP round trip). `POST_ONLY` is not supported: `postOnly: 'yes'` is refused with `post_only_not_allowed_error` on mainnet as on demo, so it raises before signing. The reply is the accepted order (`NEW`); execution is asynchronous, so nothing filled is reported. A refusal is a `4xx` with a `label` (`mark_price_limit_exceeded_error`, `insufficient_funds_error`, `post_only_not_allowed_error`): nothing rests.

# %%
async def place_order(market_id: str, /, order: Order, *, settings: Settings = {}) -> OrderResponse:
  if order['type'] == 'POST_ONLY':
    raise NotImplementedError('EVEDEX refuses post-only orders')
  qty, price = Decimal(order['qty']), Decimal(order['price'])
  positions = (await client.exchange.positions.list())['list']
  leverage = next((p['leverage'] for p in positions if p['instrument'] == market_id), 1)
  placed = await client.exchange.orders.place_limit(
    instrument=market_id,
    side='BUY' if qty > 0 else 'SELL',
    leverage=leverage,
    quantity=abs(qty),
    limit_price=price,
    time_in_force='IOC' if order['type'] == 'MARKET' else None,
    id=order.get('client_order_id') or order_id(),
  )
  return OrderResponse(id=placed['id'], details=placed)


# not executed: state-changing; verified by the owner's mainnet lifecycle run (poc/lifecycle.py, 2026-11-19)
mark = table['XRPUSD']['markPrice']
await place_order('XRPUSD', {'type': 'LIMIT', 'qty': Decimal('6'), 'price': (mark * Decimal('0.97')).quantize(Decimal('0.0001'))})


# %% [markdown]
# ## `cancel_order`
#
# `exchange.orders.cancel`: not signed. An unknown id answers `404 order_not_found_error`; an order filled before the cancel is processed stays filled.

# %%
async def cancel_order(market_id: str, /, id: str, *, settings: Settings = {}) -> Any:
  return await client.exchange.orders.cancel(id)


# not executed: state-changing; verified by the owner's mainnet lifecycle run (poc/lifecycle.py, 2026-11-19)
await cancel_order('XRPUSD', '<order id>')


# %% [markdown]
# ## `cancel_orders`
#
# The SDK default over `cancel_order` (the venue's `cancel_by_ids` answers per id with `success`, which an unknown id reads `false` without saying why).

# %%
async def cancel_orders(market_id: str, /, ids: Sequence[str], *, settings: Settings = {}) -> Any:
  return [await cancel_order(market_id, id) for id in ids]


# not executed: state-changing; verified by the owner's mainnet lifecycle run (poc/lifecycle.py, 2026-11-19)
await cancel_orders('XRPUSD', ['<order id>'])


# %% [markdown]
# ## `replace_order`
#
# The SDK default, cancel then place. The venue's `replace_limit` (signed `replace_limit_order` over id, quantity and price) answers `{}`, keeps the side and the id, and was recorded once by the owner; it is not mapped until the lifecycle run shows what it does to a partly filled order.

# %%
async def replace_order(market_id: str, /, id: str, order: Order, *, settings: Settings = {}) -> OrderResponse:
  await cancel_order(market_id, id)
  return await place_order(market_id, order)


# not executed: state-changing; verified by the owner's mainnet lifecycle run (poc/lifecycle.py, 2026-11-19)
await replace_order('XRPUSD', '<order id>', {'type': 'LIMIT', 'qty': Decimal('6'), 'price': Decimal('0.95')})


# %% [markdown]
# ## `replace_orders`
#
# The SDK default over `replace_order`.

# %%
async def replace_orders(market_id: str, /, orders: Sequence[tuple[str, Order]], *, settings: Settings = {}) -> Sequence[OrderResponse | Exception]:
  return [await replace_order(market_id, id, order) for id, order in orders]


# not executed: state-changing; verified by the owner's mainnet lifecycle run (poc/lifecycle.py, 2026-11-19)
await replace_orders('XRPUSD', [('<order id>', {'type': 'LIMIT', 'qty': Decimal('6'), 'price': Decimal('0.95')})])


# %% [markdown]
# ## `cancel_open_orders`
#
# `exchange.orders.cancel_by_instrument` (`mass-cancel`): every open order of the account on the instrument, answered `{}`.

# %%
async def cancel_open_orders(market_id: str, /, *, settings: Settings = {}) -> Any:
  return await client.exchange.orders.cancel_by_instrument(market_id)


# not executed: state-changing; verified by the owner's mainnet lifecycle run (poc/lifecycle.py, 2026-11-19)
await cancel_open_orders('XRPUSD')


# %% [markdown]
# ## `index`
#
# `exchange.market.instrument`: the index price is the base coin's `avgLastPrice` times the instrument's `lotSize` (documented on both fields; `lotSize` is 1000 on `1000PEPEUSD` and `1000BONKUSD`, 1 elsewhere).

# %%
async def index(market_id: str, /, *, settings: Settings = {}):
  row = await client.exchange.market.instrument(market_id)
  return row['from']['avgLastPrice'] * row['lotSize']


{m: (await index(m), table[m]['markPrice']) for m in [*MARKETS, '1000PEPEUSD']}


# %% [markdown]
# ## `next_funding`
#
# `exchange.market.instrument`: `fundingRate`, set at `fundingRateCreatedAt` (08:00:00.001 UTC on 2026-11-19) and computed every `fundingRateInterval` hours (8 on every instrument). Per the venue's funding page ([Funding Rate](https://docs.evedex.com/key-features-and-components/trading-platform-and-matching-engine/funding-rate)): "the funding rate (FR) is computed once every 8 hours per trading pair. Settlements occur hourly, with each hour charging/crediting a pro-rated amount of FR ÷ 8". So the next settlement is the next whole hour and charges `fundingRate / fundingRateInterval`; positive when longs pay. The public `funding-rate` channel published nothing in 15 seconds mid-period.

# %%
async def next_funding(market_id: str, /, *, ttl: timedelta | None = None) -> NextFunding:
  row = await client.exchange.market.instrument(market_id)
  now = datetime.now(timezone.utc)
  return NextFunding(
    rate=row['fundingRate'] / row['fundingRateInterval'],
    time=now.replace(minute=0, second=0, microsecond=0) + FUNDING_SETTLEMENT,
    interval=FUNDING_SETTLEMENT,
  )


{m: await next_funding(m) for m in MARKETS}


# %% [markdown]
# ## `perp_stats`
#
# One `instruments(fields='metrics')` read: index (`from.avgLastPrice * lotSize`), `markPrice`, the next hourly settlement as in `next_funding`, and `openInterest` in base units.

# %%
async def perp_stats(markets: Collection[str] | None = None, *, settings: Settings = {}, ttl: timedelta | None = None) -> Mapping[str, PerpStats]:
  rows = cast(list[Instrument], await client.exchange.market.instruments('metrics'))
  now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
  return {
    r['name']: PerpStats(
      index=r['from']['avgLastPrice'] * r['lotSize'],
      mark=r['markPrice'],
      funding=r['fundingRate'] / r['fundingRateInterval'],
      next_funding_time=now + FUNDING_SETTLEMENT,
      funding_interval=FUNDING_SETTLEMENT,
      open_interest=r['openInterest'],
    )
    for r in rows
    if r['visibility'] == 'all' and (markets is None or r['name'] in markets)
  }


await perp_stats(MARKETS)


# %% [markdown]
# ## `funding_rates`
#
# Not supported: the venue publishes the current rate only (on the instrument and on the `funding-rate` channel); no REST endpoint serves past rates.

# %%
async def funding_rates(market_id: str, /, start: datetime | None = None, end: datetime | None = None):
  raise NotImplementedError('EVEDEX publishes no funding-rate history: only the current rate')
  yield


'not supported'


# %% [markdown]
# ## `funding_payments`
#
# Not supported: `exchange.account.funding_transfers(type='fundingRate')` lists the account's funding entries, but a ledger row is `{type, coin, quantity, createdAt}`: it names no instrument, so neither a market's payments nor exchange-wide `ExchangeFundingPayment`s (which need the market) can be told apart. The account has none (2026-11-19). `positions.history` carries a closed position's total `fundingRate`, not its payments.

# %%
async def funding_payments(market_id: str | None, /, start: datetime, end: datetime) -> AsyncIterable[Sequence[FundingPayment]]:
  raise NotImplementedError("EVEDEX funding payments are not supported: the account ledger's `fundingRate` entries name no instrument")
  yield


ledger = await client.exchange.account.funding_transfers(limit=20)
{'count': ledger['count'], 'types': sorted({r['type'] for r in ledger['list']}), 'keys': sorted(ledger['list'][0]) if ledger['list'] else []}


# %% [markdown]
# ## `perp_position`
#
# `exchange.positions.list`: one record per instrument the account traded or set a leverage on, flat ones included (`quantity` 0); `quantity` is unsigned beside `side`. The venue publishes a `bankruptcyPrice` (null when flat), not a liquidation price, so `liquidation_price` stays `None`. The account is flat (XRPUSD's record is zero).

# %%
async def perp_position(market_id: str, /, *, ttl: timedelta | None = None) -> PerpPosition:
  for p in (await client.exchange.positions.list())['list']:
    if p['instrument'] == market_id and p['quantity']:
      return PerpPosition(size=-p['quantity'] if p['side'] == 'SELL' else p['quantity'], entry_price=p['avgPrice'])
  return PerpPosition()


{m: await perp_position(m) for m in MARKETS}


# %% [markdown]
# ## `leverage`
#
# The position record's `leverage`, which `set_leverage` writes and the record keeps while flat (XRPUSD: 1, restored by the owner's run). An instrument with no record has the venue's default, 1 (the leverage every order carries unless set; the client's docs: "the venue would otherwise default to 1").

# %%
async def leverage(market_id: str, /, *, ttl: timedelta | None = None) -> Decimal:
  rows = (await client.exchange.positions.list())['list']
  return Decimal(next((p['leverage'] for p in rows if p['instrument'] == market_id), 1))


{m: await leverage(m) for m in MARKETS}


# %% [markdown]
# ## `set_leverage`
#
# `exchange.positions.set_leverage(instrument, leverage=n)`: not signed (an API key suffices), works without a position, answers the record with the leverage now in force. Whole numbers from 1 to the instrument's `maxLeverage`.

# %%
async def set_leverage(market_id: str, /, leverage: Decimal):
  await client.exchange.positions.set_leverage(market_id, leverage=int(leverage))


# not executed: state-changing; verified by the owner's mainnet lifecycle run (poc/lifecycle.py, 2026-11-19)
await set_leverage('XRPUSD', Decimal(2))


# %% [markdown]
# ## `position`
#
# The perpetual position.

# %%
async def position(market_id: str, /, *, ttl: timedelta | None = None) -> Position:
  return await perp_position(market_id)


{m: await position(m) for m in MARKETS}


# %% [markdown]
# ## `perp_collateral`
#
# `exchange.account.available_balance` and `exchange.positions.list`. One cross bucket: the venue has no isolated margin mode. Equity is the trading balance (`funding.balance`, which realized PnL, fees and funding change, positions do not) plus the positions' `unRealizedPnL`; free collateral the venue's `availableBalance` (the balance less positions' and open orders' initial margin and less negative unrealized PnL); initial margin the positions' `initialMargin`; maintenance margin the positions' `maintenanceMargin`; leverage the positions' notional (`volume`) over equity.

# %%
async def perp_collateral(market_id: str | None = None, /, *, ttl: timedelta | None = None) -> PerpCollateral:
  summary = await client.exchange.account.available_balance()
  rows = (await client.exchange.positions.list())['list']
  equity = summary['funding']['balance'] + sum((p['unRealizedPnL'] for p in rows), Decimal(0))
  notional = sum((p['volume'] for p in summary['position']), Decimal(0))
  return PerpCollateral(
    equity=equity,
    free_collateral=summary['availableBalance'],
    initial_margin=sum((p['initialMargin'] for p in summary['position']), Decimal(0)),
    maintenance_margin=sum((p['maintenanceMargin'] for p in rows), Decimal(0)),
    leverage=notional / equity if notional and equity > 0 else Decimal(0),
    margin_mode='cross',
  )


await perp_collateral()


# %% [markdown]
# ## `collateral_id`
#
# The account has one trading balance backing every instrument: `<account>:perp`.

# %%
async def collateral_id(market_id: str, /) -> str:
  return 'evedex:perp'


await collateral_id('BTCUSD')


# %% [markdown]
# ## `available_notional`
#
# The SDK default, `free_collateral * leverage()`. `exchange.account.power` publishes a "largest order value" per side (7.99 beside a 7.99 balance at leverage 1), but it ignores the instrument's leverage setting unless passed one, so the default is kept.

# %%
async def available_notional(market_id: str, /, *, ttl: timedelta | None = None) -> Decimal:
  return (await perp_collateral()).free_collateral * await leverage(market_id)


{m: await available_notional(m) for m in MARKETS}


# %% [markdown]
# ## `remaining_position_limit`
#
# The instrument's `leverageLimit` maps a leverage to the largest position notional allowed at it (BTCUSD: 43.2M at 1x, 363k at 200x). At the account's leverage, less the position held in each direction, at the mark. `me.riskFactorOverride.leverageLimit` would replace the tiers for the account (empty here); which instruments it covers is undocumented, so an account with one raises. No open-interest cap is published.

# %%
async def remaining_position_limit(market_id: str, /, *, ttl: timedelta | None = None) -> RemainingPositionLimit:
  row = await client.exchange.market.instrument(market_id)
  user = await client.exchange.account.me()
  if 'leverageLimit' in user['riskFactorOverride']:
    raise NotImplementedError('per-account leverage limits')
  size = (await perp_position(market_id)).size
  lev = int(await leverage(market_id))
  return RemainingPositionLimit.capped(max_notional=row['leverageLimit'].get(str(lev)), position=size * row['markPrice'])


{m: await remaining_position_limit(m) for m in MARKETS}


# %% [markdown]
# ## `collateral`
#
# Defers to `perp_collateral`.

# %%
async def collateral(market_id: str | None = None, /, *, ttl: timedelta | None = None) -> PerpCollateral:
  return await perp_collateral(market_id)


await collateral()


# %% [markdown]
# ## Coverage
#
# Status is one of `verified` (executed live, real data), `empty` (executed live, nothing to show on this account), `blocked` (a typed-client issue, numbered in `typed-client-issues.md`), `not supported` (the venue has no such data) or `not attempted`.
#
# | method | status | note |
# |---|---|---|
# | `markets` | verified | `visibility: all`; prod |
# | `depth` | verified | REST, 100 levels a side, stamped |
# | `depth_stream` | verified | whole-book publications at `round=0.1` (each instrument's own tick) |
# | `tickers` | verified | last and volumes from one metrics read; bid/ask from one `marketLevel=1` book per market |
# | `rules` | verified | tick, step, min/max qty, min notional, standard fees, `markPriceLimit` band |
# | `fees` | verified | `me.tradingFees`, personal overrides first |
# | `candles` | verified | six SDK widths; base and USD volume |
# | `query_order` | verified | a filled order; unknown id is `None` |
# | `open_orders` | verified | lifecycle run: resting orders listed with fill progress |
# | `trades_history` | verified | the account's XRPUSD fills, side from the orders, fee from `orders.fills`; the lifecycle run's 2 round-trip fills |
# | `trades_stream` | blocked | subscribes (13:39 UTC); received none of the lifecycle run's 2 fills: prod answered every subscribe with a `temporary` code-100 error then (see `typed-client-issues.md`, "Centrifugo `temporary` subscribe errors raise the final `ApiError`"); rerun `poc/lifecycle.py --round-trip` |
# | `place_order` | verified | mainnet lifecycle run (2026-11-19, 6.6 XRP round trip): LIMIT rests, MARKET (IOC limit) fills or ends `CANCELLED`; `POST_ONLY` refused by the venue, so not supported |
# | `cancel_order` | verified | lifecycle run; a second cancel and an unknown id raise `OrderNotFound` |
# | `cancel_orders` | verified | SDK default; lifecycle run |
# | `replace_order` | verified | SDK default (cancel, then place); lifecycle run |
# | `replace_orders` | verified | SDK default over `replace_order` |
# | `cancel_open_orders` | verified | `mass-cancel`; lifecycle run |
# | `index` | verified | `avgLastPrice * lotSize` |
# | `next_funding` | verified | current rate pro-rated to the hourly settlement (docs); no payment observed yet |
# | `perp_stats` | verified | one metrics read |
# | `funding_rates` | not supported | no rate history published |
# | `funding_payments` | not supported | ledger rows name no instrument |
# | `perp_position` | verified | lifecycle run: a 6.6 XRP long at 0.9907, then flat |
# | `leverage` | verified | position record, default 1 |
# | `set_leverage` | verified | lifecycle run: 1 to 2 and back |
# | `position` | empty | flat |
# | `collateral_id` | verified | `<account>:perp` |
# | `available_notional` | verified | SDK default |
# | `remaining_position_limit` | verified | `leverageLimit` tier at the account's leverage |
# | `collateral` | verified | |
# | `perp_collateral` | verified | one cross bucket, flat account |

# %% [markdown]
# ## Catalogue
#
# Every ID the verified methods returned, minus what the catalogue translates for this platform. Anything listed is a catalogue addition to make, not something to rename here: the SDK emits venue-native IDs and the catalogue maps them.

# %%
from sdk_dev.catalogue import Ids, gap, load_catalogue

ids = Ids(perp_markets={f'perp:{m}' for m in listed}, assets={USDT})
missing = gap('evedex', ids, load_catalogue())
{'assets': missing.assets, 'perp_markets': (len(missing.perp_markets), len(listed)), 'missing': missing.perp_markets}

# %% [markdown]
# ## Cleanup

# %%
await stack.aclose()
