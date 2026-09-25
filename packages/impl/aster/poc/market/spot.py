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
  Order,
  OrderResponse,
  OrderState,
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
from typed_aster.schemas import AccountTrade, BatchError, DepthUpdate
from typed_aster.spot.trade.cancel_batch_orders import SpotBatchCancelledOrder
from typed_aster.spot.trade.schemas import SpotOrder
from tribulnation.sdk.core.stream import Subscription
from tribulnation.sdk.market import Candle
from tribulnation.sdk.market.types.candles import candle_windows
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


def order_state(row: SpotOrder) -> OrderState:
  """Preserve native order quantities and reject incomplete order responses."""
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
    client.spot.client.mainnet
    or client.spot.client.base_url != 'https://sapi.asterdex-testnet.com/api/v3'
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
    paths=('spot',),
    grep=r'market\.|streams\.partial_depth|account\.|trade\.|position\.risk|listen_key\.|user_stream\.|wallet\.transfer',
  )
)


# %% [markdown]
# ## `markets`
#
# List available markets.


# %%
async def markets() -> Sequence[str]:
  """List native active spot symbols on testnet."""
  info = await client.spot.market.exchange_info()
  return [r['symbol'] for r in info['symbols'] if r['status'] == 'TRADING']


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
  raw = await client.spot.market.depth(market_id, limit=1000)
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

  async with client.spot.streams.partial_depth(
    market_id.lower(), levels=20, speed='100ms'
  ).map(to_book) as upstream:

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
  stats = await client.spot.market.ticker_24hr()
  quotes = await client.spot.market.book_ticker()
  stats = stats if isinstance(stats, list) else [stats]
  quotes = quotes if isinstance(quotes, list) else [quotes]
  books = {r['symbol']: r for r in quotes}
  symbols = (await client.spot.market.exchange_info())['symbols']
  wanted = {r['symbol'] for r in symbols if r['status'] == 'TRADING'}
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
active = set(await markets())
assert set(all_tickers) <= active
(
  len(all_tickers),
  sorted(active - set(all_tickers)),
  await tickers(MARKETS),
  await tickers([]),
)


# %% [markdown]
# ## `rules`
#
# Fetch the market rules.


# %%
async def rules(market_id: str, /, *, refetch: bool = False) -> Rules:
  """Read native filters and the standard quote fee asset, excluding ASTER discounts."""
  row = next(
    r
    for r in (await client.spot.market.exchange_info())['symbols']
    if r['symbol'] == market_id
  )
  price = next(f for f in row['filters'] if f['filterType'] == 'PRICE_FILTER')
  lot = next(f for f in row['filters'] if f['filterType'] == 'LOT_SIZE')
  notionals = [
    f['minNotional']
    for f in row['filters']
    if f['filterType'] == 'MIN_NOTIONAL' or f['filterType'] == 'NOTIONAL'
  ]
  percent = next(
    (f for f in row['filters'] if f['filterType'] == 'PERCENT_PRICE'), None
  )
  return Rules(
    fee_asset=row['quoteAsset'],
    tick_size=price['tickSize'],
    step_size=lot['stepSize'],
    fixed_min_qty=lot['minQty'] or None,
    max_qty=lot['maxQty'] or None,
    fixed_min_price=price['minPrice'] or None,
    fixed_max_price=price['maxPrice'] or None,
    min_value=max(notionals) if notionals else None,
    rel_min_price=percent['multiplierDown'] if percent else None,
    rel_max_price=percent['multiplierUp'] if percent else None,
    api=row['status'] == 'TRADING',
    fees=None,
    details=row,
  )


# Fee units: https://docs.asterdex.com/trading/spot/spot-fee-structure
{m: await rules(m) for m in MARKETS}


# %% [markdown]
# ## `fees`
#
# Fetch the selected market's account rates without a standard-rate fallback.


# %%
async def fees(market_id: str, /, *, refetch: bool = False) -> Fees:
  """Read this account's native maker and taker commission rates."""
  row = await client.spot.account.commission_rate(market_id)
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
    rows = await client.spot.market.klines(
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
    row = await client.spot.trade.order(symbol=market_id, order_id=int(id))
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
  return [order_state(r) for r in await client.spot.trade.open_orders(market_id)]


{m: await open_orders(m) for m in MARKETS}


# %% [markdown]
# ## `trades_history`
#
# Fetch your trades history.


# %%
async def trades_history(
  market_id: str, /, start: datetime, end: datetime
) -> AsyncIterable[Sequence[Trade]]:
  """Do not return a partial history when confirmed testnet buys are missing."""
  raise NotImplementedError(
    'Testnet spot user_trades omits confirmed buy fills; see dev-docs/aster-market.md'
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
  key = (await client.spot.listen_key.start())['listenKey']

  async def keepalive():
    """Renew the stream lease before its native expiry."""
    while True:
      await asyncio.sleep(25 * 60)
      await client.spot.listen_key.keepalive(key)

  renewal = asyncio.create_task(keepalive())
  try:
    async with client.spot.user_stream.events(key) as upstream:

      async def fills() -> AsyncGenerator[Trade]:
        """Ignore status changes and other symbols; never count cumulative fills twice."""
        async for event in upstream:
          if event['e'] != 'executionReport':
            continue
          r = event
          if r['s'] != market_id or r['x'] != 'TRADE':
            continue

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
    await client.spot.listen_key.close(key)


# %% [markdown]
# ## `position`
#
# Fetch your open position in the market.


# %%
async def position(market_id: str, /) -> Position:
  """Do not report zero when the testnet omits known funded spot balances."""
  raise NotImplementedError(
    'Testnet spot account.info omits funded balances; see dev-docs/aster-market.md'
  )


try:
  await position('ASTERUSDT')
except NotImplementedError as exc:
  print(str(exc))


# %% [markdown]
# ## `collateral`
#
# Fetch collateral.


# %%
async def collateral(market_id: str | None = None, /) -> Collateral:
  """Wait for an accurate native spot balance view before reporting collateral."""
  raise NotImplementedError(
    'Testnet spot account.info omits funded balances; see dev-docs/aster-market.md'
  )


try:
  await collateral('ASTERUSDT')
except NotImplementedError as exc:
  print(str(exc))


# %% [markdown]
# ## `available_notional`
#
# Fetch the max. notional position you can open.


# %%
# Unavailable: No native account-side buy/sell capacity; no derived buying-power estimate
async def available_notional(market_id: str, /):
  """No native account-side buy/sell capacity; no derived buying-power estimate."""
  raise NotImplementedError(
    'No native account-side buy/sell capacity; no derived buying-power estimate'
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
    row = await client.spot.trade.place_order(
      {
        'symbol': market_id,
        'side': 'BUY' if qty > 0 else 'SELL',
        'type': 'MARKET',
        'quantity': abs(qty),
      }
    )
  else:
    price = Decimal(str(order['price']))
    if not price.is_finite() or price <= 0:
      raise ValueError('Limit price must be finite and positive')
    row = await client.spot.trade.place_order(
      {
        'symbol': market_id,
        'side': 'BUY' if qty > 0 else 'SELL',
        'type': 'LIMIT',
        'quantity': abs(qty),
        'price': price,
        'timeInForce': 'GTX' if order['type'] == 'POST_ONLY' else 'GTC',
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
  return await client.spot.trade.cancel_order(symbol=market_id, order_id=int(id))


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
  results: list[SpotBatchCancelledOrder | BatchError] = []
  for offset in range(0, len(ids), 10):
    results.extend(
      await client.spot.trade.cancel_batch_orders(
        market_id, order_id_list=[int(id) for id in ids[offset : offset + 10]]
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
  return await client.spot.trade.cancel_all_open_orders(market_id)


# %% [markdown]
# ## Authorized testnet order lifecycle
#
# Execute all order mutations, the 10-order batch boundary, positive query/open-order branches and buy/sell fills. Subscribe before trading, reconcile each streamed fill to REST history, and clean up in `finally`.

# %%
from decimal import ROUND_FLOOR, ROUND_CEILING
import time
from typing_extensions import Literal


# The testnet account endpoint currently omits funded balances. The receipt in
# transaction_history proves whether this dedicated fixture was already seeded.
funding_rows = await client.spot.account.transaction_history(
  type='TRANSFER_FUTURE_TO_SPOT'
)
if not any(r['asset'] == 'USDT' and r['balanceDelta'] >= 250 for r in funding_rows):
  require_testnet()
  print(
    'Spot test funding:',
    await client.futures.wallet.transfer(
      Decimal('250'),
      asset='USDT',
      client_tran_id=f'sdk-poc-{time.time_ns()}',
      kind_type='FUTURE_SPOT',
    ),
  )

symbol = 'ASTERUSDT'
require_testnet()
assert not await open_orders(symbol), 'The lifecycle expects no pre-existing orders'
# Track only this test's executed quantity for cleanup, not an invented SDK balance.
fixture_base = Decimal(0)
info = next(
  r
  for r in (await client.spot.market.exchange_info())['symbols']
  if r['symbol'] == symbol
)
step = next(f['stepSize'] for f in info['filters'] if f['filterType'] == 'LOT_SIZE')
tick = next(f['tickSize'] for f in info['filters'] if f['filterType'] == 'PRICE_FILTER')
min_notional = next(
  f['minNotional'] for f in info['filters'] if f['filterType'] == 'MIN_NOTIONAL'
)
book = await client.spot.market.book_ticker(symbol)
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
    (1, 'LIMIT'),
    (-1, 'LIMIT'),
  )
  async with trades_stream(symbol) as stream:
    iterator = aiter(stream)
    for case, (side, order_type) in enumerate(cases):
      # Spot sells only the quantity available after native base-asset fees.
      amount = qty
      if side < 0:
        amount = (fixture_base / step).to_integral_value(rounding=ROUND_FLOOR) * step
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
          fixture_base += fill.qty
          if fill.fee and fill.fee.asset == 'ASTER':
            fixture_base -= fill.fee.amount
      state = await wait_order(placed.id, active=False)
      assert state and not state.active and state.filled_qty == side * amount
      evidence[f'{case}_order'] = state
      evidence[f'{case}_stream'] = observed
      if case == 0:
        sell_price = (book['askPrice'] * Decimal('1.02') / tick).to_integral_value(
          rounding=ROUND_CEILING
        ) * tick
        sell_qty = (fixture_base / step).to_integral_value(rounding=ROUND_FLOOR) * step
        sell = await place_order(
          symbol, {'type': 'POST_ONLY', 'qty': -sell_qty, 'price': sell_price}
        )
        sell_state = await wait_order(sell.id, active=True)
        assert sell_state.qty == -sell_qty and sell_state.filled_qty == 0
        await cancel_order(symbol, sell.id)
        assert not (await wait_order(sell.id, active=False)).active
        evidence['post_only_sell'] = sell_state
      if side > 0:
        evidence['account_after_buy'] = (await client.spot.account.info())['balances']
    await client.spot.listen_key.keepalive()
  # Allow asynchronous REST indexing, then retain any missing trade IDs as a
  # venue defect rather than replacing history with cached websocket events.
  history_rows: list[AccountTrade] = []
  missing: set[str | None] = set()
  for attempt in range(20):
    finished = datetime.now(timezone.utc)
    history_rows = await client.spot.trade.user_trades(
      symbol, start_time=started, end_time=finished, limit=1000
    )
    missing = {r.id for r in streamed} - {str(r['id']) for r in history_rows}
    if not missing:
      break
    await asyncio.sleep(0.5)
  by_id = {str(r['id']): r for r in history_rows}
  for fill in streamed:
    if fill.id in by_id:
      match = by_id[fill.id]
      assert (fill.qty, fill.price, fill.time, fill.maker, fill.fee) == (
        match['qty'] if match['side'] == 'BUY' else -match['qty'],
        match['price'],
        match['time'],
        match['maker'],
        Trade.Fee(amount=match['commission'], asset=match['commissionAsset']),
      )
  evidence['missing_history_ids'] = sorted(id for id in missing if id is not None)
  evidence['native_history'] = [
    {k: r[k] for k in ('id', 'side', 'qty', 'price', 'commission', 'commissionAsset')}
    for r in history_rows
  ]
finally:
  await cancel_open_orders(symbol)
  await wait_open_count(0)
  # Spot trading fees can leave sub-step dust; only sell executable quantity.
  remaining = fixture_base
  executable = (remaining / step).to_integral_value(rounding=ROUND_FLOOR) * step
  if executable * resting_price >= min_notional:
    await place_order(symbol, {'type': 'MARKET', 'qty': -executable, 'price': 0})
  await wait_open_count(0)
  assert not await open_orders(symbol)
evidence['account_after'] = (await client.spot.account.info())['balances']
evidence['fixture_base_dust'] = fixture_base
evidence


# %% [markdown]
# ## Coverage
#
# Testnet only. Mutating cells ran with explicit user authorization. Blocked
# methods fail explicitly; independent native probes retain the failure evidence.
#
# | method | status | note |
# |---|---|---|
# | `markets` | verified | 6 native spot symbols |
# | `depth` | verified | BTCUSDT and ASTERUSDT; native base quantities, top 5 from REST |
# | `depth_stream` | verified | Two BTCUSDT top-5 snapshots from native partial depth; cap 20 |
# | `tickers` | verified | Only published tickers for active symbols; missing tickers are not synthesized |
# | `rules` | verified | Explicit price/lot filters; standard fee asset; public fee rates unknown |
# | `fees` | verified | Native account maker/taker commission rates for BTCUSDT and ASTERUSDT |
# | `candles` | verified | All six SDK intervals on BTCUSDT/ASTERUSDT; 510 one-minute rows cross the 500-row boundary |
# | `query_order` | verified | Missing, resting, filled and cancelled native orders; signed buy/sell quantities |
# | `open_orders` | verified | Resting orders observed; confirmed empty after cancellation |
# | `trades_history` | blocked | Native REST omits confirmed buys; pagination also sends exclusive filters; dev-docs/aster-market.md and typed-client-issues.md |
# | `trades_stream` | verified | Four real buy/sell fills with native fees; REST matching checked for returned sells; listen-key cleanup |
# | `position` | blocked | Native account.info returns balances=[] after funding and fills; dev-docs/aster-market.md |
# | `collateral` | blocked | Native account.info omits funded USDT and ASTER balances; dev-docs/aster-market.md |
# | `available_notional` | not supported | No native account-side buy/sell capacity; no derived buying-power estimate |
# | `place_order` | verified | Real MARKET and marketable GTC fills on both sides; resting GTX buys and sells |
# | `cancel_order` | verified | Single resting buy and post-only sell cancelled and queried |
# | `cancel_orders` | verified | Eleven resting orders cancelled across the ten-order batch limit; empty input |
# | `cancel_open_orders` | verified | Two resting orders removed; waits for the confirmed REST state |

# %% [markdown]
# ## Catalogue
#
# Every ID the verified methods returned, minus what the catalogue translates for this platform. Anything listed is a catalogue addition to make, not something to rename here: the SDK emits venue-native IDs and the catalogue maps them.

# %%
from sdk_dev.catalogue import Ids, gap, load_catalogue

listed = await markets()
rows = (await client.spot.market.exchange_info())['symbols']
ids = Ids(
  spot_markets={f'spot:{m}' for m in listed},
  assets={
    a for r in rows if r['symbol'] in listed for a in (r['baseAsset'], r['quoteAsset'])
  },
)
gap('aster', ids, load_catalogue(root=repo_root()))

# %% [markdown]
# ## Native trade-history pagination failure
#
# The sell fills returned by REST are enough to exercise continuation independently of the missing buys.

# %%
pagination_rows = 0
try:
  async for page in client.spot.trade.user_trades_paged(
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
    'Paginator now completes; missing buy fills must also be resolved before mapping history'
  )

# %%
await client.__aexit__(None, None, None)  # pyright: ignore[reportUnknownMemberType] -- upstream lifecycle parameters are untyped
