# %% [markdown]
# # aster `market` PoC
#
# Maps `typed_aster` onto the SDK `market` surface, one method per cell, qualified against the funded testnet wallet where coverage says so. The rules, and how a typed-client issue is reported in `typed-client-issues.md`, are in `.agents/skills/sdk-poc/SKILL.md`.
#
# Uses `mainnet=False` and the dedicated local `.env` created for this PoC.
# Private cells require the registered, faucet-funded testnet agent.
# The user explicitly authorized testnet mutations. The lifecycle cell places and cancels orders, opens and closes positions, and checks streamed fills against history.

# %%
from datetime import datetime, timedelta, timezone
from typing_extensions import (
  Any,
  AsyncGenerator,
  AsyncIterable,
  Collection,
  Mapping,
  Sequence,
)
from dotenv import dotenv_values
from sdk_dev.repo import repo_root
from typed_aster import Aster
from tribulnation.sdk.market import (
  Book,
  CandleInterval,
  Collateral,
  Fees,
  NextFunding,
  Order,
  OrderResponse,
  OrderState,
  PerpCollateral,
  PerpPosition,
  PerpStats,
  Position,
  Rules,
  Settings,
  Ticker,
  Trade,
)
from tribulnation.sdk.market.exchange import OverflowPolicy
import asyncio
from contextlib import asynccontextmanager, suppress
from decimal import Decimal
from typed_aster import BadRequest
from typed_aster.schemas import BatchError, DepthUpdate
from typed_aster.futures.trade.schemas import FuturesOrder
from tribulnation.sdk.core.stream import Subscription
from tribulnation.sdk.market import Candle
from tribulnation.sdk.market.types.candles import candle_windows
from tribulnation.sdk.market import FundingRate, FundingPayment
from pydantic import TypeAdapter
from typing_extensions import TypedDict

credentials = dotenv_values(repo_root() / 'packages/impl/aster/poc/.env')
client = await Aster.new(
  mainnet=False,
  public=not bool(credentials.get('ASTER_SIGNER_PRIVATE_KEY')),
  user=credentials.get('ASTER_USER'),
  signer=credentials.get('ASTER_SIGNER_PRIVATE_KEY'),
).__aenter__()

MARKETS = ['BTCUSDT', 'ASTERUSDT']

end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
start = end - timedelta(days=7)


def order_state(row: FuturesOrder) -> OrderState:
  """Preserve native order quantities and reject incomplete order responses."""
  if 'price' not in row or 'origQty' not in row or 'executedQty' not in row:
    raise NotImplementedError('Order response lacks SDK quantities or price')
  sign = 1 if row['side'] == 'BUY' else -1
  return OrderState(
    id=str(row['orderId']),
    price=row['price'],
    qty=sign * row['origQty'],
    filled_qty=sign * row['executedQty'],
    active=row['status'] in ('NEW', 'PARTIALLY_FILLED'),
    details=row,
  )


class ErrorBody(TypedDict):
  """Only the documented error fields, without a request URL or credentials."""

  code: int
  msg: str


error_body = TypeAdapter(ErrorBody)


def require_testnet():
  """Keep every mutating helper on the authorized testnet transport."""
  if (
    client.futures.client.mainnet
    or client.futures.client.base_url != 'https://fapi.asterdex-testnet.com/fapi/v3'
  ):
    raise RuntimeError('This PoC may only mutate the Aster testnet')


# %% [markdown]
# ## Surface
#
# What the client exposes. Widen or narrow the filter until every endpoint the mapping below uses is listed here.

# %%
from sdk_dev.surface import surface

print(
  surface(
    'typed_aster',
    'Aster',
    paths=('futures',),
    grep=r'market\.|streams\.partial_depth|account\.|trade\.|position\.risk|listen_key\.|user_stream\.|wallet\.transfer',
  )
)


# %% [markdown]
# ## `markets`
#
# List available markets.


# %%
async def markets() -> Sequence[str]:
  """List native active perp symbols on testnet."""
  info = await client.futures.market.exchange_info()
  return [
    r['symbol']
    for r in info['symbols']
    if r['status'] == 'TRADING' and r['contractType'] == 'PERPETUAL'
  ]


listed = await markets()
len(listed), listed


# %% [markdown]
# ## `depth`
#
# Fetch the market order book.


# %%
async def depth(market_id: str, /, *, levels: int | None = None) -> Book:
  """Read native base-unit book quantities, then trim to the requested depth."""
  if levels is not None and not 1 <= levels <= 1000:
    raise ValueError('levels must be between 1 and 1000')
  raw = await client.futures.market.depth(market_id, limit=1000)
  book = Book(
    bids=[Book.Entry(*r) for r in raw['bids']],
    asks=[Book.Entry(*r) for r in raw['asks']],
  )
  return book if levels is None else book.limit(levels)


{m: await depth(m, levels=5) for m in MARKETS}


# %% [markdown]
# ## `depth_stream`
#
# Subscribe to the market order book.


# %%
@asynccontextmanager
async def depth_stream(
  market_id: str,
  /,
  *,
  levels: int | None = None,
  queue_size: int = 1,
  overflow: OverflowPolicy = 'latest',
) -> AsyncGenerator[AsyncIterable[Book]]:
  """Map the native top-20 snapshots with the SDK's bounded queue policy."""
  if levels is not None and not 1 <= levels <= 20:
    raise NotImplementedError('This PoC qualifies partial snapshots up to 20 levels')

  def to_book(row: DepthUpdate) -> Book:
    """Convert one complete partial-depth snapshot."""
    book = Book(
      bids=[Book.Entry(*r) for r in row['b']], asks=[Book.Entry(*r) for r in row['a']]
    )
    return book if levels is None else book.limit(levels)

  async with client.futures.streams.partial_depth(market_id.lower(), levels=20).map(
    to_book
  ) as upstream:

    async def subscribe() -> Subscription.Context[Book]:
      """Borrow the upstream owned by the surrounding context."""

      async def unsubscribe():
        """The surrounding context owns socket cleanup."""

      return Subscription.Context(aiter(upstream), unsubscribe)

    async with Subscription(subscribe).subscribe(
      queue_size=queue_size, overflow=overflow
    ) as stream:
      yield stream


async with depth_stream('BTCUSDT', levels=5) as stream:
  iterator = aiter(stream)
  books = [await asyncio.wait_for(anext(iterator), 15) for _ in range(2)]
books


# %% [markdown]
# ## `tickers`
#
# Fetch a ticker snapshot for many markets at once.


# %%
async def tickers(
  markets: Collection[str] | None = None, *, settings: Settings = {}
) -> Mapping[str, Ticker]:
  """Join native rolling volume and best-book fields by symbol."""
  if markets is not None and not markets:
    return {}
  stats = await client.futures.market.ticker_24hr()
  quotes = await client.futures.market.book_ticker()
  stats = stats if isinstance(stats, list) else [stats]
  quotes = quotes if isinstance(quotes, list) else [quotes]
  books = {r['symbol']: r for r in quotes}
  symbols = (await client.futures.market.exchange_info())['symbols']
  wanted = {
    r['symbol']
    for r in symbols
    if r['status'] == 'TRADING' and r['contractType'] == 'PERPETUAL'
  }
  if markets is not None:
    wanted.intersection_update(markets)
  result: dict[str, Ticker] = {}
  for row in stats:
    if row['symbol'] not in wanted:
      continue
    quote = books.get(row['symbol'])
    result[row['symbol']] = Ticker(
      last=row['lastPrice'],
      base_volume_24h=row['volume'],
      quote_volume_24h=row['quoteVolume'],
      bid=quote['bidPrice'] if quote else None,
      ask=quote['askPrice'] if quote else None,
      bid_qty=quote['bidQty'] if quote else None,
      ask_qty=quote['askQty'] if quote else None,
    )
  return result


all_tickers = await tickers()
assert set(all_tickers) == set(await markets())
len(all_tickers), await tickers(MARKETS), await tickers([])


# %% [markdown]
# ## `rules`
#
# Fetch the market rules.


# %%
async def rules(market_id: str, /, *, refetch: bool = False) -> Rules:
  """Map explicit futures filters; leave the public fee schedule unknown."""
  row = next(
    r
    for r in (await client.futures.market.exchange_info())['symbols']
    if r['symbol'] == market_id
  )
  price = next(f for f in row['filters'] if f['filterType'] == 'PRICE_FILTER')
  lot = next(f for f in row['filters'] if f['filterType'] == 'LOT_SIZE')
  notional = next(
    (f for f in row['filters'] if f['filterType'] == 'MIN_NOTIONAL'), None
  )
  percent = next(
    (f for f in row['filters'] if f['filterType'] == 'PERCENT_PRICE'), None
  )
  return Rules(
    fee_asset=row['marginAsset'],
    tick_size=price['tickSize'],
    step_size=lot['stepSize'],
    fixed_min_qty=lot['minQty'] or None,
    max_qty=lot['maxQty'] or None,
    fixed_min_price=price['minPrice'] or None,
    fixed_max_price=price['maxPrice'] or None,
    min_value=notional['notional'] if notional else None,
    rel_min_price=percent['multiplierDown'] if percent else None,
    rel_max_price=percent['multiplierUp'] if percent else None,
    api=row['status'] == 'TRADING',
    fees=None,
    details=row,
  )


{m: await rules(m) for m in MARKETS}


# %% [markdown]
# ## `fees`
#
# Fetch the selected market's account rates without a standard-rate fallback.


# %%
async def fees(market_id: str, /, *, refetch: bool = False) -> Fees:
  """Read this account's native maker and taker commission rates."""
  row = await client.futures.account.commission_rate(market_id)
  return Fees.symmetric(
    maker=row['makerCommissionRate'], taker=row['takerCommissionRate']
  )


{m: await fees(m) for m in MARKETS}


# %% [markdown]
# ## `candles`
#
# Fetch the market's historical trade candles.


# %%
async def candles(
  market_id: str, /, interval: CandleInterval, start: datetime, end: datetime
) -> AsyncIterable[Sequence[Candle]]:
  """Read half-open trade-candle windows without filling empty intervals."""
  for lower, upper in candle_windows(start, end, interval, size=500):
    rows = await client.futures.market.klines(
      market_id,
      interval=interval,
      start_time=lower,
      end_time=upper - timedelta(milliseconds=1),
      limit=500,
    )
    yield [
      Candle(
        time=r[0],
        open=r[1],
        high=r[2],
        low=r[3],
        close=r[4],
        volume=r[5],
        quote_volume=r[7],
        trades=r[8],
      )
      for r in rows
      if start <= r[0] < end
    ]


candle_counts: dict[str, dict[str, int]] = {}
intervals: tuple[CandleInterval, ...] = ('1m', '5m', '15m', '1h', '4h', '1d')
for m in MARKETS:
  candle_counts[m] = {}
  for interval in intervals:
    lower = end - (timedelta(minutes=510) if interval == '1m' else timedelta(days=7))
    rows = [r async for page in candles(m, interval, lower, end) for r in page]
    assert len({r.time for r in rows}) == len(rows)
    assert all(lower <= r.time < end for r in rows)
    assert rows
    candle_counts[m][interval] = len(rows)
candle_counts


# %% [markdown]
# ## `query_order`
#
# Fetch the state of the order with the given ID.


# %%
async def query_order(market_id: str, /, id: str) -> OrderState | None:
  """Return None only for the venue's documented nonexistent-order code."""
  try:
    row = await client.futures.trade.order({'symbol': market_id, 'orderId': int(id)})
  except BadRequest as exc:
    if len(exc.args) > 1 and error_body.validate_python(exc.args[1])['code'] == -2013:
      return None
    raise
  return order_state(row)


# The lifecycle cell below also verifies resting, filled and cancelled orders.
{m: await query_order(m, '1') for m in MARKETS}


# %% [markdown]
# ## `open_orders`
#
# Fetch your currently open orders.


# %%
async def open_orders(market_id: str, /) -> Sequence[OrderState]:
  """Map the account's validated open orders on this symbol."""
  return [order_state(r) for r in await client.futures.trade.open_orders(market_id)]


{m: await open_orders(m) for m in MARKETS}


# %% [markdown]
# ## `trades_history`
#
# Fetch your trades history.


# %%
async def trades_history(
  market_id: str, /, start: datetime, end: datetime
) -> AsyncIterable[Sequence[Trade]]:
  """Wait for the typed paginator to stop combining mutually exclusive filters."""
  raise NotImplementedError(
    'UserTrades.user_trades_paged combines exclusive time and ID filters; see typed-client-issues.md'
  )
  yield []  # Retain the SDK async-generator contract for the blocked method.


try:
  async for page in trades_history('ASTERUSDT', start, end):
    pass
except NotImplementedError as exc:
  print(str(exc))


# %% [markdown]
# ## `trades_stream`
#
# Subscribe to your real-time trades.


# %%
@asynccontextmanager
async def trades_stream(
  market_id: str, /, *, queue_size: int = 1000, overflow: OverflowPolicy = 'fail'
) -> AsyncGenerator[AsyncIterable[Trade]]:
  """Map last-fill events, owning one account listen key for this PoC session."""
  require_testnet()
  key = (await client.futures.listen_key.start())['listenKey']

  async def keepalive():
    """Renew the stream lease before its native expiry."""
    while True:
      await asyncio.sleep(25 * 60)
      await client.futures.listen_key.keepalive()

  renewal = asyncio.create_task(keepalive())
  try:
    async with client.futures.user_stream.events(key) as upstream:

      async def fills() -> AsyncGenerator[Trade]:
        """Ignore status changes and other symbols; never count cumulative fills twice."""
        async for event in upstream:
          if event['e'] == 'listenKeyExpired':
            raise RuntimeError('The Aster listen key expired')
          if event['e'] != 'ORDER_TRADE_UPDATE':
            continue
          r = event['o']
          if r['s'] != market_id or r['x'] != 'TRADE':
            continue
          if (
            'l' not in r or 'L' not in r or 'T' not in r or 't' not in r or 'm' not in r
          ):
            raise NotImplementedError('Fill event lacks last-fill fields')
          fee = None
          if 'n' in r and 'N' in r:
            fee = Trade.Fee(amount=r['n'], asset=r['N'])
          elif 'n' in r or 'N' in r:
            raise NotImplementedError(
              'Commission amount and asset must arrive together'
            )
          yield Trade(
            id=str(r['t']),
            price=r['L'],
            qty=r['l'] if r['S'] == 'BUY' else -r['l'],
            time=r['T'],
            maker=r['m'],
            fee=fee,
            details=r,
          )

      async def subscribe() -> Subscription.Context[Trade]:
        """Bind the bounded SDK queue to the validated event iterator."""
        iterator = fills()
        return Subscription.Context(iterator, iterator.aclose)

      async with Subscription(subscribe).subscribe(
        queue_size=queue_size, overflow=overflow
      ) as stream:
        yield stream
  finally:
    renewal.cancel()
    with suppress(asyncio.CancelledError):
      await renewal
    await client.futures.listen_key.close()


# %% [markdown]
# ## `position`
#
# Fetch your open position in the market.


# %%
async def position(market_id: str, /) -> Position:
  """Use the venue's signed one-way position amount, including native zero."""
  rows = await client.futures.position.risk(market_id)
  if len(rows) != 1 or rows[0]['positionSide'] != 'BOTH':
    raise NotImplementedError('Only one-way positions are qualified by this PoC')
  return Position(size=rows[0]['positionAmt'])


{m: await position(m) for m in MARKETS}


# %% [markdown]
# ## `available_notional`
#
# Fetch the max. notional position you can open.


# %%
# Unavailable: No account-side buy/sell capacity figure; remaining_openable_notional_value is a symbol-wide cap
async def available_notional(market_id: str, /):
  """No account-side buy/sell capacity figure; remaining_openable_notional_value is a symbol-wide cap."""
  raise NotImplementedError(
    'No account-side buy/sell capacity figure; remaining_openable_notional_value is a symbol-wide cap'
  )


try:
  await available_notional('ASTERUSDT')
except NotImplementedError as exc:
  print(str(exc))
else:
  raise AssertionError('Review coverage: the method is no longer unavailable')


# %% [markdown]
# ## `place_order`
#
# Place an order in the market.


# %%
async def place_order(
  market_id: str, /, order: Order, *, settings: Settings = {}
) -> OrderResponse:
  """Map signed base quantity and native MARKET, GTC and GTX order types."""
  require_testnet()
  if settings:
    raise NotImplementedError('Aster-specific settings are not declared in the SDK')
  qty = Decimal(str(order['qty']))
  if not qty.is_finite() or not qty:
    raise ValueError('Order quantity must be finite and nonzero')
  if order['type'] == 'MARKET':
    row = await client.futures.trade.place_order(
      {
        'symbol': market_id,
        'side': 'BUY' if qty > 0 else 'SELL',
        'type': 'MARKET',
        'quantity': abs(qty),
        'newOrderRespType': 'RESULT',
      }
    )
  else:
    price = Decimal(str(order['price']))
    if not price.is_finite() or price <= 0:
      raise ValueError('Limit price must be finite and positive')
    row = await client.futures.trade.place_order(
      {
        'symbol': market_id,
        'side': 'BUY' if qty > 0 else 'SELL',
        'type': 'LIMIT',
        'quantity': abs(qty),
        'price': price,
        'timeInForce': 'GTX' if order['type'] == 'POST_ONLY' else 'GTC',
        'newOrderRespType': 'RESULT',
      }
    )
  return OrderResponse(id=str(row['orderId']), details=row)


# %% [markdown]
# ## `cancel_order`
#
# Cancel an order in the market.


# %%
async def cancel_order(market_id: str, /, id: str, *, settings: Settings = {}) -> Any:
  """Cancel one native order and return the venue acknowledgement."""
  require_testnet()
  if settings:
    raise NotImplementedError('Aster-specific settings are not declared in the SDK')
  return await client.futures.trade.cancel_order(
    {'symbol': market_id, 'orderId': int(id)}
  )


# %% [markdown]
# ## `cancel_orders`
#
# Cancel multiple orders in the market.


# %%
async def cancel_orders(
  market_id: str, /, ids: Sequence[str], *, settings: Settings = {}
) -> Any:
  """Chunk at the native ten-order limit, preserving every per-order result."""
  require_testnet()
  if settings:
    raise NotImplementedError('Aster-specific settings are not declared in the SDK')
  results: list[FuturesOrder | BatchError] = []
  for offset in range(0, len(ids), 10):
    results.extend(
      await client.futures.trade.cancel_batch_orders(
        {
          'symbol': market_id,
          'orderIdList': [int(id) for id in ids[offset : offset + 10]],
        }
      )
    )
  return results


# %% [markdown]
# ## `cancel_open_orders`
#
# Cancel all open orders in the market.


# %%
async def cancel_open_orders(market_id: str, /, *, settings: Settings = {}) -> Any:
  """Cancel all orders for the selected native symbol."""
  require_testnet()
  if settings:
    raise NotImplementedError('Aster-specific settings are not declared in the SDK')
  return await client.futures.trade.cancel_all_open_orders(market_id)


# %% [markdown]
# ## `index`
#
# Fetch the market index price.


# %%
async def index(market_id: str, /, *, settings: Settings = {}) -> Decimal:
  """Read the venue's index price directly from premiumIndex."""
  row = await client.futures.market.premium_index(market_id)
  if isinstance(row, list):
    row = next(r for r in row if r['symbol'] == market_id)
  return row['indexPrice']


{m: await index(m) for m in MARKETS}


# %% [markdown]
# ## `next_funding`
#
# Fetch the next funding rate and time.


# %%
async def next_funding(market_id: str, /) -> NextFunding:
  """Read the native funding quote, settlement time and per-symbol interval."""
  row = await client.futures.market.premium_index(market_id)
  if isinstance(row, list):
    row = next(r for r in row if r['symbol'] == market_id)
  config = next(
    r
    for r in await client.futures.market.funding_info(market_id)
    if r['symbol'] == market_id
  )
  return NextFunding(
    rate=row['lastFundingRate'],
    time=row['nextFundingTime'],
    interval=timedelta(hours=config['fundingIntervalHours']),
  )


{m: await next_funding(m) for m in MARKETS}


# %% [markdown]
# ## `perp_stats`
#
# Fetch a pricing and funding snapshot for many markets at once.


# %%
# Unavailable: blocked by FundingInfo null configuration fields; see typed-client-issues.md
async def perp_stats(
  markets: Collection[str] | None = None, *, settings: Settings = {}
) -> Mapping[str, PerpStats]:
  """Wait for the client to validate the complete native funding configuration."""
  raise NotImplementedError(
    'FundingInfo configuration fields are null on some testnet response rows'
  )


try:
  await perp_stats()
except NotImplementedError as exc:
  print(str(exc))
else:
  raise AssertionError('Review coverage: the method is no longer unavailable')


# %% [markdown]
# ## `funding_rates`
#
# Fetch the market's historical funding rates.


# %%
async def funding_rates(
  market_id: str, /, start: datetime | None = None, end: datetime | None = None
) -> AsyncIterable[Sequence[FundingRate]]:
  """Page actual funding settlements without calculating a substitute rate."""
  async for page in client.futures.market.funding_rate_paged(
    market_id, start_time=start, end_time=end, limit=1000
  ):
    yield [FundingRate(rate=r['fundingRate'], time=r['fundingTime']) for r in page]


{m: [r async for page in funding_rates(m, start, end) for r in page] for m in MARKETS}


# %% [markdown]
# ## `funding_payments`
#
# Fetch your funding payments history.


# %%
async def funding_payments(
  market_id: str, /, start: datetime, end: datetime
) -> AsyncIterable[Sequence[FundingPayment]]:
  """Negate venue income so SDK positive means funding paid."""
  async for page in client.futures.account.income_paged(
    market_id, income_type='FUNDING_FEE', start_time=start, end_time=end, limit=1000
  ):
    yield [FundingPayment(amount=-r['income'], time=r['time']) for r in page]


{
  m: [r async for page in funding_payments(m, start, end) for r in page]
  for m in MARKETS
}


# %% [markdown]
# ## `perp_position`
#
# Fetch your open position in the perpetual market.


# %%
async def perp_position(market_id: str, /) -> PerpPosition:
  """Read the native signed amount and entry price for one-way positions."""
  rows = await client.futures.position.risk(market_id)
  if len(rows) != 1 or rows[0]['positionSide'] != 'BOTH':
    raise NotImplementedError('Only one-way positions are qualified by this PoC')
  return PerpPosition(size=rows[0]['positionAmt'], entry_price=rows[0]['entryPrice'])


{m: await perp_position(m) for m in MARKETS}


# %% [markdown]
# ## `collateral`
#
# Fetch collateral (defers to `perp_collateral`).


# %%
async def collateral(market_id: str | None = None, /) -> Collateral:
  """Read native USDT equity and available margin for the shared cross bucket."""
  if market_id is not None:
    positions = await client.futures.position.risk(market_id)
    if not positions or any(row['marginType'] != 'cross' for row in positions):
      raise NotImplementedError('The API does not expose isolated available collateral')
  row = await client.futures.account.info_with_join_margin()
  return Collateral(
    equity=row['totalMarginBalance'], free_collateral=row['availableBalance']
  )


{market: await collateral(market) for market in (None, *MARKETS)}


# %% [markdown]
# ## `perp_collateral`
#
# Fetch perpetual collateral.


# %%
# Unavailable: The API publishes configured leverage, not the SDK aggregate notional/equity leverage figure
async def perp_collateral(market_id: str | None = None, /) -> PerpCollateral:
  """The API publishes configured leverage, not the SDK aggregate notional/equity leverage figure."""
  raise NotImplementedError(
    'The API publishes configured leverage, not the SDK aggregate notional/equity leverage figure'
  )


try:
  await perp_collateral()
except NotImplementedError as exc:
  print(str(exc))
else:
  raise AssertionError('Review coverage: the method is no longer unavailable')


# %% [markdown]
# ## Authorized testnet order lifecycle
#
# Execute all order mutations, the 10-order batch boundary, positive query/open-order branches and buy/sell fills. Subscribe before trading, reconcile each streamed fill to REST history, and clean up in `finally`.

# %%
from decimal import ROUND_FLOOR, ROUND_CEILING
from typing_extensions import Literal


symbol = 'ASTERUSDT'
require_testnet()
assert not await open_orders(symbol), 'The lifecycle expects no pre-existing orders'
baseline = (await position(symbol)).size
assert baseline == 0, 'The lifecycle expects a flat reference market'
info = next(
  r
  for r in (await client.futures.market.exchange_info())['symbols']
  if r['symbol'] == symbol
)
step = next(f['stepSize'] for f in info['filters'] if f['filterType'] == 'LOT_SIZE')
tick = next(f['tickSize'] for f in info['filters'] if f['filterType'] == 'PRICE_FILTER')
min_notional = next(
  f['notional'] for f in info['filters'] if f['filterType'] == 'MIN_NOTIONAL'
)
book = await client.futures.market.book_ticker(symbol)
if isinstance(book, list):
  book = next(r for r in book if r['symbol'] == symbol)
resting_price = (book['bidPrice'] * Decimal('0.98') / tick).to_integral_value(
  rounding=ROUND_FLOOR
) * tick
qty = ((min_notional * 2 / resting_price) / step).to_integral_value(
  rounding=ROUND_CEILING
) * step
started = datetime.now(timezone.utc) - timedelta(seconds=1)
evidence: dict[str, object] = {}
streamed: list[Trade] = []


async def wait_order(id: str, *, active: bool) -> OrderState:
  """Wait for the signed REST view to catch up with the mutation acknowledgement."""
  async with asyncio.timeout(10):
    while True:
      state = await query_order(symbol, id)
      if state is not None and state.active == active:
        return state
      await asyncio.sleep(0.2)


async def wait_open_count(count: int):
  """Bound propagation delay after cancel-all instead of treating ACK as finality."""
  async with asyncio.timeout(10):
    while len(await open_orders(symbol)) != count:
      await asyncio.sleep(0.2)


try:
  resting = await place_order(
    symbol, {'type': 'LIMIT', 'qty': qty, 'price': resting_price}
  )
  state = await wait_order(resting.id, active=True)
  assert state and state.active and state.qty == qty and state.filled_qty == 0
  assert resting.id in {r.id for r in await open_orders(symbol)}
  evidence['resting'] = state
  await cancel_order(symbol, resting.id)
  state = await wait_order(resting.id, active=False)
  assert state and not state.active and state.filled_qty == 0
  evidence['cancel_order'] = state

  batch = [
    await place_order(symbol, {'type': 'POST_ONLY', 'qty': qty, 'price': resting_price})
    for _ in range(11)
  ]
  cancelled = await cancel_orders(symbol, [r.id for r in batch])
  assert len(cancelled) == 11
  for placed in batch:
    state = await wait_order(placed.id, active=False)
    assert state and not state.active and state.filled_qty == 0
  assert await cancel_orders(symbol, []) == []
  evidence['cancel_orders'] = {'orders': len(cancelled), 'empty_input': True}

  for _ in range(2):
    await place_order(symbol, {'type': 'LIMIT', 'qty': qty, 'price': resting_price})
  await wait_open_count(2)
  await cancel_open_orders(symbol)
  await wait_open_count(0)
  assert not await open_orders(symbol)
  evidence['cancel_open_orders'] = 2

  cases: tuple[tuple[int, Literal['MARKET', 'LIMIT']], ...] = (
    (1, 'MARKET'),
    (-1, 'MARKET'),
    (-1, 'MARKET'),
    (1, 'MARKET'),
    (1, 'LIMIT'),
    (-1, 'LIMIT'),
  )
  expected_size = Decimal(0)
  async with trades_stream(symbol) as stream:
    iterator = aiter(stream)
    for case, (side, order_type) in enumerate(cases):
      amount = qty
      crossing_price = (
        (
          book['askPrice'] * Decimal('1.02')
          if side > 0
          else book['bidPrice'] * Decimal('0.98')
        )
        / tick
      ).to_integral_value(rounding=ROUND_FLOOR) * tick
      placed = await place_order(
        symbol, {'type': order_type, 'qty': side * amount, 'price': crossing_price}
      )
      observed: list[Trade] = []
      total = Decimal(0)
      async with asyncio.timeout(20):
        while abs(total) < amount:
          fill = await anext(iterator)
          assert fill.qty * side > 0
          observed.append(fill)
          streamed.append(fill)
          total += fill.qty
      state = await wait_order(placed.id, active=False)
      assert state and not state.active and state.filled_qty == side * amount
      evidence[f'{case}_order'] = state
      evidence[f'{case}_stream'] = observed
      if case == 0:
        sell_price = (book['askPrice'] * Decimal('1.02') / tick).to_integral_value(
          rounding=ROUND_CEILING
        ) * tick
        sell_qty = qty
        sell = await place_order(
          symbol, {'type': 'POST_ONLY', 'qty': -sell_qty, 'price': sell_price}
        )
        sell_state = await wait_order(sell.id, active=True)
        assert sell_state.qty == -sell_qty and sell_state.filled_qty == 0
        await cancel_order(symbol, sell.id)
        assert not (await wait_order(sell.id, active=False)).active
        evidence['post_only_sell'] = sell_state
      expected_size += side * amount
      assert (await position(symbol)).size == expected_size
      detailed = await perp_position(symbol)
      assert detailed.size == expected_size
      if expected_size:
        assert detailed.entry_price > 0
        evidence[f'{case}_position'] = detailed
        evidence[f'{case}_collateral'] = await collateral()
    await client.futures.listen_key.keepalive()
  finished = datetime.now(timezone.utc)
  # One native page checks these few fills only. The separate pagination
  # diagnostic below blocks SDK history; no replacement paginator is invented.
  native_rows = await client.futures.trade.user_trades(
    symbol, start_time=started, end_time=finished, limit=1000
  )
  history_rows: list[Trade] = []
  for row in native_rows:
    if (
      'side' not in row
      or 'maker' not in row
      or 'commission' not in row
      or 'commissionAsset' not in row
    ):
      raise NotImplementedError('Native fill fields are incomplete')
    history_rows.append(
      Trade(
        id=str(row['id']),
        qty=row['qty'] if row['side'] == 'BUY' else -row['qty'],
        price=row['price'],
        time=row['time'],
        maker=row['maker'],
        fee=Trade.Fee(amount=row['commission'], asset=row['commissionAsset']),
      )
    )
  assert any(r.qty > 0 for r in history_rows) and any(r.qty < 0 for r in history_rows)
  by_id = {r.id: r for r in history_rows}
  for fill in streamed:
    match = by_id[fill.id]
    assert (fill.qty, fill.price, fill.time, fill.maker, fill.fee) == (
      match.qty,
      match.price,
      match.time,
      match.maker,
      match.fee,
    )
  assert (
    sum((r.qty for r in history_rows), Decimal(0))
    == (await position(symbol)).size - baseline
  )
  evidence['history'] = history_rows
finally:
  await cancel_open_orders(symbol)
  await wait_open_count(0)
  remaining = (await position(symbol)).size
  if remaining:
    await place_order(symbol, {'type': 'MARKET', 'qty': -remaining, 'price': 0})
  assert (await position(symbol)).size == 0
  assert not await open_orders(symbol)
evidence['position_after'] = await position(symbol)
evidence


# %% [markdown]
# ## Coverage
#
# Testnet only. Mutating cells ran with explicit user authorization. Blocked
# methods fail explicitly; independent native probes retain the failure evidence.
#
# | method | status | note |
# |---|---|---|
# | `markets` | verified | 17 active perpetual symbols |
# | `depth` | verified | BTCUSDT and ASTERUSDT; native base quantities, top 5 from REST |
# | `depth_stream` | verified | Two BTCUSDT top-5 snapshots from native partial depth; cap 20 |
# | `tickers` | verified | Native price, volume and book fields; filtered and empty selections |
# | `rules` | verified | Explicit price/lot filters; standard fee asset; public fee rates unknown |
# | `fees` | verified | Native account maker/taker commission rates for BTCUSDT and ASTERUSDT |
# | `candles` | verified | All six SDK intervals on BTCUSDT/ASTERUSDT; 510 one-minute rows cross the 500-row boundary |
# | `query_order` | verified | Missing, resting, filled and cancelled native orders; signed buy/sell quantities |
# | `open_orders` | verified | Resting orders observed; confirmed empty after cancellation |
# | `trades_history` | blocked | UserTrades.user_trades_paged combines exclusive time and ID filters; typed-client-issues.md |
# | `trades_stream` | verified | Six real fills matched to one native REST page, including time, fee asset and maker flag; listen-key cleanup |
# | `position` | verified | Nonzero long, short and flat one-way positions |
# | `available_notional` | not supported | No native account-side buy/sell capacity; no derived buying-power estimate |
# | `place_order` | verified | Real MARKET and marketable GTC fills on both sides; resting GTX buys and sells |
# | `cancel_order` | verified | Single resting buy and post-only sell cancelled and queried |
# | `cancel_orders` | verified | Eleven resting orders cancelled across the ten-order batch limit; empty input |
# | `cancel_open_orders` | verified | Two resting orders removed; waits for the confirmed REST state |
# | `index` | verified | Native premium_index indexPrice for BTCUSDT and ASTERUSDT |
# | `next_funding` | verified | Native indicative rate and next time; 8h BTC and 4h ASTER intervals |
# | `perp_stats` | blocked | FundingInfo configuration fields are null on some testnet response rows; typed-client-issues.md |
# | `funding_rates` | verified | Native settlements over seven days; no inferred premium |
# | `funding_payments` | empty | Live call returned no funding cashflows; test positions were closed before settlement |
# | `perp_position` | verified | Native long/short quantities and positive entry prices; flat after cleanup |
# | `collateral` | verified | Native join-margin equity/available collateral; account-wide and selected cross-margin markets |
# | `perp_collateral` | not supported | The API publishes configured leverage, not the SDK aggregate notional/equity leverage figure |

# %% [markdown]
# ## Catalogue
#
# Every ID the verified methods returned, minus what the catalogue translates for this platform. Anything listed is a catalogue addition to make, not something to rename here: the SDK emits venue-native IDs and the catalogue maps them.

# %%
from sdk_dev.catalogue import Ids, gap, load_catalogue

listed = await markets()
rows = (await client.futures.market.exchange_info())['symbols']
ids = Ids(
  perp_markets={f'perp:{m}' for m in listed},
  assets={r['marginAsset'] for r in rows if r['symbol'] in listed},
)
# Instrument base identities, including 1000-token multipliers, are checked through
# perp_markets. They are not wallet asset IDs emitted by these verified methods.
gap('aster', ids, load_catalogue(root=repo_root()))

# %% [markdown]
# ## Funding configuration validation evidence
#
# The method above stays blocked. This diagnostic calls the unmodified typed endpoint.

# %%
from typed_aster import ValidationError

try:
  await client.futures.market.funding_info()
except ValidationError:
  print(
    'FundingInfo rejected null fundingIntervalHours/fundingFeeCap/fundingFeeFloor; see typed-client-issues.md'
  )
else:
  print(
    'FundingInfo now validates; re-run and map perp_stats before removing the issue'
  )

{m: await client.futures.market.funding_info(m) for m in MARKETS}

# %% [markdown]
# ## Native trade-history pagination failure
#
# Use two rows per page to exercise the continuation with real fills. The unmodified typed paginator sends time filters together with `fromId` on page two.

# %%
pagination_rows = 0
try:
  async for page in client.futures.trade.user_trades_paged(
    'ASTERUSDT',
    start_time=datetime.now(timezone.utc) - timedelta(days=1),
    end_time=datetime.now(timezone.utc),
    limit=2,
  ):
    pagination_rows += len(page)
except BadRequest as exc:
  error = error_body.validate_python(exc.args[1])
  if error['code'] != -1106:
    raise
  print({'rows_before_failure': pagination_rows, 'error': error})
else:
  print(
    'Paginator now completes; re-run and map trades_history before removing the issue'
  )

# %%
await client.__aexit__(None, None, None)  # pyright: ignore[reportUnknownMemberType] -- upstream lifecycle parameters are untyped
