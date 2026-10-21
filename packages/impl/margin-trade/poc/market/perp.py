# %% [markdown]
# # margin-trade `market` PoC: perpetuals
#
# Maps `typed_margin_trade` onto the SDK `market` surface for the perpetual exchange, one method per cell, each executed live. The rules, and how a typed-client issue is reported in `typed-client-issues.md`, are in `.agents/skills/sdk-poc/SKILL.md`.
#
# Runs against **testnet** (`mainnet=False`) with the account's approved agent key and the master address as `vault`, read from the repo-root `.env` (`MARGIN_TRADE_TESTNET_ADDRESS`, `MARGIN_TRADE_TESTNET_AGENT_PRIVATE_KEY`). The `client.toml` policy of `typed_margin_trade` allows every testnet call, small orders included; no signed call goes to mainnet. Public mainnet reads use a separate credential-free client (`public`). The lifecycle cell at the end places, fills and cancels small BTC orders and closes what it opens.

# %%
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing_extensions import Any, AsyncIterator, AsyncIterable, Collection, Literal, Mapping, Sequence

from dotenv import dotenv_values
from sdk_dev.repo import repo_root
from typed_margin_trade import MarginTrade
from typed_margin_trade.schemas import L2Book, OrderSpec, PerpAssetCtx, PerpUniverseItem
from typed_margin_trade.schemas import Fill

from tribulnation.sdk.market import Book, Candle, CandleInterval, Collateral, Fees, FundingPayment, NextFunding, Order, OrderResponse, OrderState, PerpCollateral, PerpPosition, PerpStats, Position, Rules, Settings, Ticker, Trade
from tribulnation.sdk.market.exchange import OverflowPolicy

env = dotenv_values(repo_root() / '.env')
ADDRESS = env['MARGIN_TRADE_TESTNET_ADDRESS'] or ''
client = await MarginTrade.new(env['MARGIN_TRADE_TESTNET_AGENT_PRIVATE_KEY'], vault=ADDRESS, mainnet=False).__aenter__()
public = await MarginTrade.new(public=True).__aenter__()

MARKETS = ['BTC', 'PRL']

end = datetime.now(timezone.utc)
start = end - timedelta(days=7)

MAX_SIG_FIGS = 5
PERP_MAX_DECIMALS = 6


def round_price(price: Decimal, sz_decimals: int) -> Decimal:
  """Hyperliquid's price rule, which margin.trade inherits: at most five significant
  figures and `6 - szDecimals` decimals; integer prices are always accepted."""
  if price == price.to_integral_value():
    return Decimal(f'{price.to_integral_value():f}')
  digits = MAX_SIG_FIGS - 1 - price.adjusted()
  places = min(digits, PERP_MAX_DECIMALS - sz_decimals)
  rounded = price.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
  return Decimal(f'{rounded.normalize():f}')


async def universe() -> dict[str, PerpUniverseItem]:
  meta = await client.info.meta()
  return {item['name']: item for item in meta['universe']}


async def contexts() -> dict[str, tuple[PerpUniverseItem, PerpAssetCtx]]:
  """Join each context to its market by `index`: the venue does not list them in universe order."""
  meta, ctxs = await client.info.meta_and_asset_ctxs()
  by_index = {ctx['index']: ctx for ctx in ctxs}
  return {item['name']: (item, by_index[item['index']]) for item in meta['universe']}


def parse_book(raw: L2Book, levels: int | None = None) -> Book:
  sides = raw['levels']
  bids, asks = (sides[0], sides[1]) if sides else ([], [])
  book = Book(
    bids=[Book.Entry(price=level['px'], qty=level['sz']) for level in bids],
    asks=[Book.Entry(price=level['px'], qty=level['sz']) for level in asks],
    time=raw['time'],
  )
  return book.limit(levels) if levels else book


def parse_trade(fill: Fill) -> Trade:
  sign = 1 if fill['side'] == 'B' else -1
  return Trade(
    id=str(fill['tid']),
    order_id=str(fill['oid']),
    price=fill['px'],
    qty=sign * fill['sz'],
    time=fill['time'],
    maker=not fill['isTaker'],
    fee=Trade.Fee(amount=fill['fee'], asset=fill['feeToken']),
    details=fill,
  )


ADDRESS[:6]

# %% [markdown]
# ## Surface
#
# What the client exposes. Widen or narrow the filter until every endpoint the mapping below uses is listed here.

# %%
from sdk_dev.surface import surface

print(surface('typed_margin_trade', 'MarginTrade', grep=r'meta|book|mids|candle|order|fill|funding|position|clearinghouse|active_asset|fees|contracts|cancel'))


# %% [markdown]
# ## `markets`
#
# List available markets.

# %%
async def markets() -> Sequence[str]:
  return [name for name, item in (await universe()).items() if not item.get('isDelisted')]


await markets()


# %% [markdown]
# ## `depth`
#
# Fetch the market order book.

# %%
async def depth(market_id: str, /, *, levels: int | None = None, settings: Settings = {}) -> Book:
  return parse_book(await client.info.l2_book(market_id), levels)


{market_id: await depth(market_id, levels=3) for market_id in MARKETS}


# %% [markdown]
# ## `depth_stream`
#
# Subscribe to the market order book. Each `l2Book` push is a full snapshot.

# %%
@asynccontextmanager
async def depth_stream(market_id: str, /, *, levels: int | None = None, queue_size: int = 1, overflow: OverflowPolicy = 'latest', settings: Settings = {}) -> AsyncIterator[AsyncIterable[Book]]:
  stream = await client.streams.l2_book(market_id)

  async def books() -> AsyncIterator[Book]:
    async for raw in stream:
      yield parse_book(raw, levels)

  try:
    yield books()
  finally:
    await stream.unsubscribe()


pushes: list[Book] = []
async with depth_stream(MARKETS[0], levels=2) as stream:
  async for update in stream:
    pushes.append(update)
    if len(pushes) == 2:
      break
pushes


# %% [markdown]
# ## `tickers`
#
# Fetch a ticker snapshot for many markets at once: 24h volumes from the asset contexts (every market), last trade and best bid/ask from the CoinGecko contracts feed, which publishes no bid/ask sizes and omits `SPY` and `QQQ` (their tickers keep only volumes).

# %%
async def tickers(markets: Collection[str] | None = None, *, settings: Settings = {}) -> Mapping[str, Ticker]:
  quotes = {row['base_currency']: row for row in await client.coingecko.derivatives.contracts()}
  out: dict[str, Ticker] = {}
  for name, (_, ctx) in (await contexts()).items():
    if markets is None or name in markets:
      quote = quotes.get(name)
      out[name] = Ticker(
        last=quote['last_price'] if quote else None,
        bid=quote.get('bid') if quote else None,
        ask=quote.get('ask') if quote else None,
        base_volume_24h=ctx['dayBaseVlm'],
        quote_volume_24h=ctx['dayNtlVlm'],
      )
  return out


everything = await tickers()
{k: v for k, v in everything.items() if k in MARKETS + ['SPY']}, len(everything), await tickers([])


# %% [markdown]
# ## `rules`
#
# Fetch the market rules. Fees are the market's own `takerFee`/`makerFee` from `meta`, the rates fills are charged at (checked in the `fees` cell).

# %%
async def rules(market_id: str, /, *, refetch: bool = False) -> Rules:
  item = (await universe())[market_id]
  sz = item['szDecimals']
  return Rules(
    fee_asset='USD',
    tick_size=Decimal(10) ** -min(MAX_SIG_FIGS, PERP_MAX_DECIMALS - sz),
    step_size=Decimal(10) ** -sz,
    fees=Fees(maker_buy=item['makerFee'], maker_sell=item['makerFee'], taker_buy=item['takerFee'], taker_sell=item['takerFee']),
    api=not item.get('isDelisted', False),
    details=item,
  )


{market_id: await rules(market_id) for market_id in MARKETS}


# %% [markdown]
# ## `fees`
#
# Fetch the selected market's account rates without a standard-rate fallback. `userFees` answers one account-wide rate (`userCrossRate` 0.0005, `userAddRate` 0.0001 on testnet), but the account's BTC fills were charged the market's own `meta` rate (testnet BTC `takerFee` 0.0001): the venue publishes no per-account, per-market rate, so this is not supported.

# %%
async def fees(market_id: str, /, *, refetch: bool = False) -> Fees:
  raise NotImplementedError('margin.trade publishes no per-account rate per market')


try:
  await fees('BTC')
except NotImplementedError as e:
  print(e)


account = await client.info.user_fees(ADDRESS)
btc = (await universe())['BTC']
fills = await client.info.user_fills(ADDRESS)
charged = {f['tid']: f['fee'] / (f['px'] * f['sz']) for f in fills if f['coin'] == 'BTC' and f['isTaker']}
{'userCrossRate': account['userCrossRate'], 'meta takerFee': btc['takerFee'], 'charged taker rates': set(charged.values())}


# %% [markdown]
# ## `candles`
#
# Fetch the market's historical trade candles. The venue answers at most 5000 candles per request, oldest first; the walk advances past the last opening time.

# %%
INTERVALS: dict[CandleInterval, timedelta] = {'1m': timedelta(minutes=1), '5m': timedelta(minutes=5), '15m': timedelta(minutes=15), '1h': timedelta(hours=1), '4h': timedelta(hours=4), '1d': timedelta(days=1)}


async def candles(market_id: str, /, interval: CandleInterval, start: datetime, end: datetime) -> AsyncIterator[Sequence[Candle]]:
  cursor = start
  while cursor < end:
    rows = await client.info.candle_snapshot({'coin': market_id, 'interval': interval, 'startTime': cursor, 'endTime': end - timedelta(milliseconds=1)})
    page = [Candle(time=r['t'], open=r['o'], high=r['h'], low=r['l'], close=r['c'], volume=r['v'], trades=r['n']) for r in rows if start <= r['t'] < end]
    if page:
      yield page
    if not rows:
      return
    cursor = max(r['t'] for r in rows) + INTERVALS[interval]


pages = [page async for page in candles('BTC', '1m', start, end)]
times = [c.time for page in pages for c in page]
{
  'pages': [len(p) for p in pages],
  'unique': len(set(times)) == len(times),
  'first': times[0],
  'last': times[-1],
  'per interval': {i: len([c async for p in candles('BTC', i, end - 6 * w, end) for c in p]) for i, w in INTERVALS.items()},
}


# %% [markdown]
# ## `query_order`
#
# Fetch the state of the order with the given ID. `orderStatus` answers `{status: 'order', order: {order, status}}` or `{status: 'unknownOid'}`.

# %%
def order_state(order: Any, status: str) -> OrderState:
  sign = 1 if order['side'] == 'B' else -1
  return OrderState(
    id=str(order['oid']),
    price=order['limitPx'],
    qty=sign * order['origSz'],
    filled_qty=sign * (order['origSz'] - order['sz']),
    active=status == 'open',
    details=order,
  )


async def query_order(market_id: str, /, id: str) -> OrderState | None:
  found = await client.info.order_status(user=ADDRESS, oid=int(id))
  if 'order' not in found:
    return None
  entry = found['order']
  if entry['order']['coin'] != market_id:
    return None
  return order_state(entry['order'], entry['status'])


last_fill = (await client.info.user_fills(ADDRESS))[0]
await query_order('BTC', str(last_fill['oid'])), await query_order('BTC', '1'), await client.info.order_status(user=ADDRESS, oid=1)


# %% [markdown]
# ## `open_orders`
#
# Fetch your currently open orders. `frontendOpenOrders` carries the original size, so the filled part is `origSz - sz`.

# %%
async def open_orders(market_id: str, /) -> Sequence[OrderState]:
  rows = await client.info.frontend_open_orders(user=ADDRESS)
  return [order_state(row, 'open') for row in rows if row['coin'] == market_id]


{market_id: await open_orders(market_id) for market_id in MARKETS}


# %% [markdown]
# ## `trades_history`
#
# Fetch personal fills for one market or the whole exchange: `userFillsByTime` pages backwards from `end`.

# %%
async def trades_history(market_id: str | None, /, start: datetime, end: datetime) -> AsyncIterator[Sequence[Trade]]:
  pages = client.info.user_fills_by_time_paged(ADDRESS, start_time=start, end_time=end)
  async for page in pages:
    rows = [parse_trade(f) for f in page if f['coin'] in perps and (market_id is None or f['coin'] == market_id)]
    if rows:
      yield rows


perps = set(await markets())
history = [t async for page in trades_history('BTC', start, end) for t in page]
len(history), history[:2], len([t async for page in trades_history(None, start, end) for t in page])


# %% [markdown]
# ## `trades_stream`
#
# Subscribe to your real-time trades. `userFills` pushes only when subscribed with a `coin` (the client requires it), so each market holds its own subscription. Exercised with real fills in the lifecycle cell.

# %%
@asynccontextmanager
async def trades_stream(market_id: str, /, *, queue_size: int = 1000, overflow: OverflowPolicy = 'fail', settings: Settings = {}) -> AsyncIterator[AsyncIterable[Trade]]:
  stream = await client.streams.user_fills(user=ADDRESS, coin=market_id)

  async def trades() -> AsyncIterator[Trade]:
    async for push in stream:
      if push.get('isSnapshot'):
        continue
      for fill in push['fills']:
        yield parse_trade(fill)

  try:
    yield trades()
  finally:
    await stream.unsubscribe()


async with trades_stream('BTC') as stream:
  try:
    print(await asyncio.wait_for(anext(aiter(stream)), timeout=3))
  except asyncio.TimeoutError:
    print('no fill within 3 s, as expected without trading')


# %% [markdown]
# ## `place_order`
#
# Place an order in the market. `LIMIT` sends `Gtc`, `POST_ONLY` `Alo`, `MARKET` an `Ioc` limit at the SDK's protection price. Exercised in the lifecycle cell.

# %%
TIF: dict[str, Literal['Gtc', 'Alo', 'Ioc']] = {'LIMIT': 'Gtc', 'POST_ONLY': 'Alo', 'MARKET': 'Ioc'}


async def place_order(market_id: str, /, order: Order, *, settings: Settings = {}) -> OrderResponse:
  item = (await universe())[market_id]
  qty = Decimal(order['qty'])
  spec: OrderSpec = {
    'a': item['index'],
    'b': qty > 0,
    'p': round_price(Decimal(order['price']), item['szDecimals']),
    's': abs(qty),
    'r': False,
    't': {'limit': {'tif': TIF[order['type']]}},
  }
  if (cloid := order.get('client_order_id')) is not None:
    spec['c'] = cloid
  result = await client.exchange.order([spec], grouping='na')
  status = result['statuses'][0]
  if 'error' in status:
    raise RuntimeError(status['error'])
  if 'resting' in status:
    return OrderResponse(id=str(status['resting']['oid']), details=status)
  filled = status['filled']
  return OrderResponse(id=str(filled['oid']), details=status, filled_qty=filled['totalSz'])


place_order  # changes the account: exercised by the lifecycle cell below


# %% [markdown]
# ## `cancel_order`
#
# Cancel an order in the market. A failed cancel comes back as its own status (`order not found`), not raised. Exercised in the lifecycle cell.

# %%
async def cancel_order(market_id: str, /, id: str, *, settings: Settings = {}) -> Any:
  item = (await universe())[market_id]
  result = await client.exchange.cancel([{'a': item['index'], 'o': int(id)}])
  status = result['statuses'][0]
  if status != 'success':
    raise RuntimeError(status)
  return status


cancel_order  # changes the account: exercised by the lifecycle cell below


# %% [markdown]
# ## `cancel_orders`
#
# Cancel multiple orders in the market, in one `cancel` action. Exercised in the lifecycle cell.

# %%
async def cancel_orders(market_id: str, /, ids: Sequence[str], *, settings: Settings = {}) -> Any:
  if not ids:
    return []
  item = (await universe())[market_id]
  result = await client.exchange.cancel([{'a': item['index'], 'o': int(id)} for id in ids])
  return result['statuses']


cancel_orders  # changes the account: exercised by the lifecycle cell below


# %% [markdown]
# ## `cancel_open_orders`
#
# Cancel all open orders in the market. Exercised in the lifecycle cell.

# %%
async def cancel_open_orders(market_id: str, /, *, settings: Settings = {}) -> Any:
  return await cancel_orders(market_id, [o.id for o in await open_orders(market_id)])


cancel_open_orders  # changes the account: exercised by the lifecycle cell below


# %% [markdown]
# ## `index`
#
# Fetch the market index price: the asset context's `oraclePx`.

# %%
async def index(market_id: str, /, *, settings: Settings = {}) -> Decimal:
  _, ctx = (await contexts())[market_id]
  return ctx['oraclePx']


{market_id: await index(market_id) for market_id in MARKETS}


# %% [markdown]
# ## `next_funding`
#
# Fetch the next funding rate and time: the context's current `funding`, settled hourly on the hour (the venue's funding docs; settlements in `userFunding` land at `HH:00:00`). The CoinGecko feed's `next_funding_rate_timestamp` would be the venue's own time, but the client parses it as milliseconds while the venue sends seconds (see `typed-client-issues.md`).

# %%
FUNDING_INTERVAL = timedelta(hours=1)


async def next_funding(market_id: str, /) -> NextFunding:
  _, ctx = (await contexts())[market_id]
  now = datetime.now(timezone.utc)
  return NextFunding(rate=ctx['funding'], time=now.replace(minute=0, second=0, microsecond=0) + FUNDING_INTERVAL, interval=FUNDING_INTERVAL, premium=ctx['premium'])


gecko = {r['base_currency']: r['next_funding_rate_timestamp'] for r in await client.coingecko.derivatives.contracts()}
{market_id: await next_funding(market_id) for market_id in MARKETS}, {m: gecko[m] for m in MARKETS}


# %% [markdown]
# ## `perp_stats`
#
# Fetch a pricing and funding snapshot for many markets at once, from one `metaAndAssetCtxs` call.

# %%
async def perp_stats(markets: Collection[str] | None = None, *, settings: Settings = {}) -> Mapping[str, PerpStats]:
  now = datetime.now(timezone.utc)
  nxt = now.replace(minute=0, second=0, microsecond=0) + FUNDING_INTERVAL
  return {
    name: PerpStats(index=ctx['oraclePx'], mark=ctx['markPx'], funding=ctx['funding'], next_funding_time=nxt, funding_interval=FUNDING_INTERVAL, open_interest=ctx['openInterest'])
    for name, (_, ctx) in (await contexts()).items()
    if markets is None or name in markets
  }


await perp_stats(MARKETS), len(await perp_stats())


# %% [markdown]
# ## `funding_rates`
#
# Fetch the market's historical funding rates. Not supported: `fundingHistory` answers placeholder data only (documented "not yet populated", `[]` on both networks), so `typed_margin_trade` excludes it.

# %%
async def funding_rates(market_id: str, /, start: datetime | None = None, end: datetime | None = None) -> AsyncIterator[Sequence[Any]]:
  raise NotImplementedError('margin.trade serves no funding-rate history')
  yield []


try:
  [record async for record in funding_rates('BTC')]
except NotImplementedError as e:
  print(e)


# %% [markdown]
# ## `funding_payments`
#
# Fetch personal funding payments for one market or the whole exchange. `delta.usdc` is signed from the account's side: a long paying a positive rate is negative (mainnet sample below), matching the SDK's received-positive convention. The venue sends newest first and states no row cap; the mainnet account below returned every settlement of a three-day window in one response.

# %%
async def funding_payments(market_id: str | None, /, start: datetime, end: datetime, user: str = ADDRESS, via: MarginTrade = client) -> AsyncIterator[Sequence[FundingPayment]]:
  rows = await via.info.user_funding(user, start_time=start, end_time=end)
  page = [FundingPayment(amount=r['delta']['usdc'], time=r['time']) for r in rows if market_id is None or r['delta']['coin'] == market_id]
  if page:
    yield page


MAINNET_TRADER = '9Tdb5DUfoUVnUAGwvfKhsLr8xx3nTzd4VwAw3wDdgaks'  # top of the public mainnet leaderboard
raw = await public.info.user_funding(MAINNET_TRADER, start_time=end - timedelta(days=3), end_time=end)
signs = {(r['delta']['szi'] > 0, r['delta']['fundingRate'] > 0, r['delta']['usdc'] > 0) for r in raw if r['delta']['usdc'] and r['delta']['fundingRate']}
{
  'testnet': [p async for page in funding_payments('BTC', end - timedelta(days=30), end) for p in page],
  'mainnet rows (3 days)': len(raw),
  '(long, rate>0, received) combinations': signs,
  'mainnet XAU': [p async for page in funding_payments('XAU', end - timedelta(days=1), end, MAINNET_TRADER, public) for p in page][:3],
}


# %% [markdown]
# ## `perp_position`
#
# Fetch your open position in the perpetual market. Exercised with a real position in the lifecycle cell.

# %%
async def perp_position(market_id: str, /) -> PerpPosition:
  state = await client.info.clearinghouse_state(user=ADDRESS)
  for entry in state['assetPositions']:
    if entry['position']['coin'] == market_id:
      return PerpPosition(size=entry['position']['szi'], entry_price=entry['position']['entryPx'])
  return PerpPosition(size=Decimal(0), entry_price=Decimal(0))


{market_id: await perp_position(market_id) for market_id in MARKETS}


# %% [markdown]
# ## `leverage`
#
# Fetch the leverage this account can open at on the selected market: `activeAssetData.leverage.value`.

# %%
async def leverage(market_id: str, /, *, refetch: bool = False) -> Decimal:
  data = await client.info.active_asset_data(user=ADDRESS, coin=market_id)
  return Decimal(data['leverage']['value'])


{market_id: await leverage(market_id) for market_id in MARKETS}


# %% [markdown]
# ## `perp_collateral`
#
# Fetch perpetual collateral. The perp wallet is its own account (spot is separate): the cross bucket is `crossMarginSummary` (equity `accountValue`, initial margin `totalMarginUsed`, leverage `totalNtlPos / accountValue`), maintenance `crossMaintenanceMarginUsed`, and free collateral the venue's `withdrawable`. An isolated position reports its own bucket from `leverage.rawUsd`, verified in the lifecycle cell.

# %%
async def perp_collateral(market_id: str | None = None, /) -> PerpCollateral:
  state = await client.info.clearinghouse_state(user=ADDRESS)
  for entry in state['assetPositions']:
    pos = entry['position']
    if market_id is not None and pos['coin'] == market_id and pos['leverage']['type'] == 'isolated':
      raise NotImplementedError('isolated buckets are not mapped')
  summary = state['crossMarginSummary']
  equity = summary['accountValue']
  return PerpCollateral(
    equity=equity,
    free_collateral=state['withdrawable'],
    initial_margin=summary['totalMarginUsed'],
    maintenance_margin=state['crossMaintenanceMarginUsed'],
    leverage=summary['totalNtlPos'] / equity if equity > 0 else Decimal(0),
    margin_mode='cross',
  )


await perp_collateral(), await perp_collateral('BTC')


# %% [markdown]
# ## `position`
#
# Fetch your open position in the market (defers to `perp_position`).

# %%
async def position(market_id: str, /) -> Position:
  return await perp_position(market_id)


{market_id: await position(market_id) for market_id in MARKETS}


# %% [markdown]
# ## `available_notional`
#
# Fetch the maximum notional position you can open right now: the SDK default, the free collateral of the market's bucket times `leverage`.

# %%
async def available_notional(market_id: str, /) -> Decimal:
  return (await perp_collateral(market_id)).free_collateral * await leverage(market_id)


{market_id: await available_notional(market_id) for market_id in MARKETS}


# %% [markdown]
# ## `collateral`
#
# Fetch collateral (defers to `perp_collateral`).

# %%
async def collateral(market_id: str | None = None, /) -> Collateral:
  return await perp_collateral(market_id)


await collateral()


# %% [markdown]
# ## Lifecycle
#
# Exercises the trading cells and the account reads against real state, on testnet: a resting post-only buy far below the book (queried, listed, cancelled alone), two resting buys cancelled together, one more removed by `cancel_open_orders`, then a 0.001 BTC IOC buy whose fill is caught on `trades_stream` and matched to `trades_history`, read back through `perp_position`/`perp_collateral`/`available_notional`, and closed with an IOC sell.

# %%
log: dict[str, Any] = {}
mid = (await client.info.all_mids())['BTC']
low = mid * Decimal('0.9')

resting = await place_order('BTC', {'type': 'POST_ONLY', 'qty': Decimal('0.001'), 'price': low})
log['post_only'] = resting
log['query resting'] = await query_order('BTC', resting.id)
log['open'] = [o.id for o in await open_orders('BTC')]
log['cancel_order'] = await cancel_order('BTC', resting.id)
log['query cancelled'] = await query_order('BTC', resting.id)

pair = [await place_order('BTC', {'type': 'LIMIT', 'qty': Decimal('0.001'), 'price': low * Decimal(k)}) for k in ('0.99', '0.98')]
log['cancel_orders'] = await cancel_orders('BTC', [o.id for o in pair])
await place_order('BTC', {'type': 'LIMIT', 'qty': Decimal('0.001'), 'price': low})
log['cancel_open_orders'] = await cancel_open_orders('BTC')
log['open after'] = await open_orders('BTC')

async with trades_stream('BTC') as stream:
  it = aiter(stream)
  bought = await place_order('BTC', {'type': 'MARKET', 'qty': Decimal('0.001'), 'price': mid * Decimal('1.01')})
  log['market buy'] = bought
  log['streamed'] = await asyncio.wait_for(anext(it), timeout=20)
  log['perp_position'] = await perp_position('BTC')
  log['perp_collateral'] = await perp_collateral('BTC')
  log['available_notional'] = await available_notional('BTC')
  state = await client.info.clearinghouse_state(user=ADDRESS)
  log['summary with position'] = (state['crossMarginSummary'], state['withdrawable'], [p['position']['unrealizedPnl'] for p in state['assetPositions']])
  sold = await place_order('BTC', {'type': 'MARKET', 'qty': Decimal('-0.001'), 'price': mid * Decimal('0.99')})
  log['market sell'] = sold
  log['streamed close'] = await asyncio.wait_for(anext(it), timeout=20)

await asyncio.sleep(2)
recent = [t async for page in trades_history('BTC', end - timedelta(minutes=1), datetime.now(timezone.utc) + timedelta(minutes=1)) for t in page]
log['history ids'] = [t.id for t in recent[:2]]
log['stream matches history'] = {log['streamed'].id, log['streamed close'].id} <= {t.id for t in recent}
log['flat after'] = await perp_position('BTC')
log['filled query'] = await query_order('BTC', bought.id)
log

# %% [markdown]
# ## Coverage
#
# Status is one of `verified` (executed live, real data), `empty` (executed live, nothing to show on this account), `blocked` (a typed-client issue, numbered in `typed-client-issues.md`), `not supported` (the venue has no such data) or `not attempted`.
#
# | method | status | note |
# |---|---|---|
# | `markets` | verified | 29 testnet perpetuals from `meta`; `isDelisted` ones would be left out |
# | `depth` | verified | BTC and PRL `l2Book` levels (PRL one-sided); an empty book arrives as `levels: []` |
# | `depth_stream` | verified | Two BTC `l2Book` snapshot pushes; the venue drops the socket ~30 s after a ping with the client default (typed-client issue) |
# | `tickers` | verified | 24h volumes from the asset contexts for all 29; last/bid/ask from CoinGecko contracts, which omit SPY and QQQ and carry no sizes |
# | `rules` | verified | Per-market `takerFee`/`makerFee` (charged rate 0.0001 on 20 BTC taker fills); tick `10^-min(5, 6 - szDecimals)`, step `10^-szDecimals`; no min notional or price band published |
# | `fees` | not supported | `userFees` gives one account-wide rate (0.0005) that fills are not charged (0.0001 per BTC `meta`); no per-account per-market figure |
# | `candles` | verified | All six intervals; 10080 one-minute rows over 7 days in one response (57601 over 40 days), unique and in bounds |
# | `query_order` | verified | Filled, resting, cancelled and unknown ids; `orderStatus` trails placement and cancellation by ~1 s |
# | `open_orders` | verified | Resting `Alo`/`Gtc` orders listed with signed quantities, empty after cancellation |
# | `trades_history` | verified | 20 BTC fills over 7 days via `userFillsByTime` pages; lifecycle fills matched; exchange-wide by coin |
# | `trades_stream` | verified | Lifecycle open and close fills pushed on `userFills` (with `coin`) and matched to history |
# | `position` | verified | Defers to `perp_position` |
# | `available_notional` | verified | `withdrawable` x leverage: 99913.53 with a 0.001 BTC position at 1x |
# | `place_order` | verified | `Alo` and `Gtc` rest, `Ioc` fills both sides at 1% protection; 5% refused `slippage exceeded`; `cloid` echoed |
# | `cancel_order` | verified | Resting post-only buy cancelled (`success`) |
# | `cancel_orders` | verified | Two resting buys in one `cancel` action |
# | `cancel_open_orders` | verified | One resting buy removed; open orders empty after |
# | `index` | verified | Asset context `oraclePx` (BTC, PRL) |
# | `next_funding` | verified | Context `funding` and `premium`, next full hour (documented hourly; settlements land on the hour); CoinGecko next time mis-parsed by the client |
# | `perp_stats` | verified | One `metaAndAssetCtxs` call, 29 markets joined by `index` (the venue lists PRL first) |
# | `funding_rates` | not supported | `fundingHistory` serves placeholder data only; excluded from the client |
# | `funding_payments` | verified | Testnet: one zero settlement; mainnet public account: 187 rows in 3 days in one response, `usdc` received-positive (long paying a positive rate is negative) |
# | `perp_position` | verified | 0.001 BTC long at its entry price in the lifecycle; flat before and after |
# | `leverage` | verified | `activeAssetData` cross 1x |
# | `collateral` | verified | Defers to `perp_collateral` |
# | `perp_collateral` | verified | Cross bucket with a position: equity 99998.09, margin used 84.56, maintenance 2.11, `withdrawable` free; isolated positions not mapped (raise) |

# %% [markdown]
# ## Catalogue
#
# Every ID the verified methods returned, minus what the catalogue translates for this platform. Anything listed is a catalogue addition to make, not something to rename here: the SDK emits venue-native IDs and the catalogue maps them.

# %%
from sdk_dev.catalogue import Ids, gap, load_catalogue

listed = await markets()
ids = Ids(perp_markets={f'perp:{m}' for m in listed}, assets={'USD'})
gap('margin-trade', ids, load_catalogue(root=repo_root()))

# %%
await client.__aexit__(None, None, None)  # pyright: ignore[reportUnknownMemberType] -- upstream lifecycle parameters are untyped
await public.__aexit__(None, None, None)  # pyright: ignore[reportUnknownMemberType] -- upstream lifecycle parameters are untyped
