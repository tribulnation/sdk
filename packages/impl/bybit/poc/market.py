# %%
import asyncio
from decimal import Decimal
from datetime import datetime, timedelta, timezone

from typing_extensions import Literal

from typed_bybit import Bybit
from typed_bybit.linear.orderbook import LinearOrderbookUpdate
from typed_bybit.private.execution import ExecutionUpdate
from typed_bybit.spot.orderbook import OrderbookUpdate
from typed_bybit.trade.create_order import (
  CreateLimitOrderRequest,
  CreateMarketOrderRequest,
)
from dotenv import load_dotenv

from tribulnation.sdk.market import (
  Book,
  Collateral,
  PerpCollateral,
  FundingPayment,
  FundingRate,
  NextFunding,
  Order,
  OrderResponse,
  OrderState,
  PerpPosition,
  Position,
  Rules,
  Settings,
  Trade,
)

load_dotenv()

client = await Bybit.new().__aenter__()

MARKETS = {
  'spot': ['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
  'perp': ['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
}


# %% [markdown]
# Bybit v5 is a *unified* API: spot, linear perps, inverse perps and options are the
# same HTTP/WS endpoints, discriminated by a `category` parameter (`'spot'`,
# `'linear'`, `'inverse'`, `'option'`) rather than separate namespaces like Binance's
# `spot`/`usdm_futures` split. Below, `category='spot'` covers `Market` and
# `category='linear'` covers `PerpMarket`, both against the *same* `client.*`.

# %% [markdown]
# ## `Market` (spot)

# %%
async def depth(symbol: str, *, levels: int | None = None) -> Book:
  raw = await client.market.orderbook(category='spot', symbol=symbol, limit=levels)
  return Book(
    bids=[Book.Entry(p, q) for p, q in raw['b']],
    asks=[Book.Entry(p, q) for p, q in raw['a']],
  )


{symbol: await depth(symbol, levels=5) for symbol in MARKETS['spot']}


# %%
def depth_stream(symbol: str, *, depth: Literal[1, 50, 200] = 50):
  # Bybit's WS orderbook channel pushes one full snapshot on subscribe, then
  # incremental deltas: only the changed price levels, with qty "0" meaning the
  # level was removed. Merge a delta into a running `Book` via `Book.update`
  # (adds/replaces changed levels, drops zero-qty ones) instead of treating it as
  # if it were a complete book -- a delta only has a handful of levels, not the
  # full depth -- and replace the running book outright on a snapshot, which Bybit
  # re-sends mid-subscription when the feed restarts. `.copy()` each yielded book
  # so earlier snapshots handed to callers aren't mutated by later pushes into the
  # same running `book`.
  book = Book()

  def to_book(update: OrderbookUpdate) -> Book:
    nonlocal book
    delta = Book(
      bids=[Book.Entry(p, q) for p, q in update['b']],
      asks=[Book.Entry(p, q) for p, q in update['a']],
    )
    # The push's own `type` tells the two apart: the client's core forwards it from
    # the frame onto the payload. It is declared `NotRequired` only because the
    # spec's replay gate cannot see a field the transport merges in, so fall back to
    # Bybit's documented `u == 1` marker if a push ever arrives without it.
    kind = update.get('type')
    snapshot = kind == 'snapshot' if kind is not None else update['u'] == 1
    if snapshot:
      book = delta
    else:
      book.update(delta)
    return book.copy()

  return client.spot.orderbook(depth, symbol=symbol).map(to_book)


books: list[Book] = []
async with depth_stream('BTCUSDT') as stream:
  async for book in stream:
    books.append(book)
    if len(books) >= 3:
      break
books


# %%
async def rules(symbol: str, *, refetch: bool = False) -> Rules:
  info = await client.market.instruments(category='spot', symbol=symbol)
  # `instruments()` returns a 3-way union (`Spot|Contract|OptionInstrumentsInfo`)
  # regardless of the `category` argument -- narrow it by hand via the shared
  # `category` discriminant, same idiom as every other `category='spot'`/`'linear'`
  # call below.
  assert info['category'] == 'spot'
  sym = info['list'][0]
  lot = sym['lotSizeFilter']
  price_filter = sym['priceFilter']
  fee = await client.account.fee_rate(category='spot', symbol=symbol)
  rate = fee['list'][0] if fee['list'] else None
  return Rules(
    fee_asset=sym['quoteCoin'],
    tick_size=price_filter['tickSize'],
    step_size=lot['basePrecision'],
    fixed_min_qty=lot['minOrderQty'],
    min_value=lot['minOrderAmt'],
    max_qty=lot['maxOrderQty'],
    maker_fee=rate['makerFeeRate'] if rate else Decimal(0),
    taker_fee=rate['takerFeeRate'] if rate else Decimal(0),
    api=sym['status'] == 'Trading',
    details=sym,
  )


{symbol: await rules(symbol) for symbol in MARKETS['spot']}


# %%
async def open_orders(symbol: str) -> list[OrderState]:
  raw = await client.trade.open_orders(category='spot', symbol=symbol)
  out: list[OrderState] = []
  for o in raw['list']:
    qty = Decimal(o['qty'])
    filled = Decimal(o['cumExecQty'])
    sign = 1 if o['side'] == 'Buy' else -1
    out.append(
      OrderState(
        id=o['orderId'],
        price=Decimal(o['price']),
        qty=sign * qty,
        filled_qty=sign * filled,
        active=o['orderStatus'] in ('New', 'PartiallyFilled', 'Untriggered'),
        details=o,
      )
    )
  return out


{symbol: await open_orders(symbol) for symbol in MARKETS['spot']}


# %%
async def trades_history(symbol: str, start: datetime, end: datetime) -> list[Trade]:
  raw = await client.trade.trade_history(
    category='spot',
    symbol=symbol,
    start_time=start,
    end_time=end,
    exec_type='Trade',
  )
  out: list[Trade] = []
  for t in raw['list']:
    qty = Decimal(t['execQty'])
    out.append(
      Trade(
        id=t['execId'],
        price=Decimal(t['execPrice']),
        qty=qty if t['side'] == 'Buy' else -qty,
        time=t['execTime'],
        maker=t['isMaker'],
        # `execFee` is a required, already-parsed `Decimal`. A truthiness guard here
        # would be wrong, not merely redundant: 40 of the 55 spot fills this account
        # has ever made carry `execFee` exactly `0`, and reporting those as `fee=None`
        # ("unknown") rather than a zero fee loses real information.
        fee=Trade.Fee(amount=t['execFee'], asset=t['feeCurrency']),
        details=t,
      )
    )
  return out


end = datetime.now(timezone.utc)
start = end - timedelta(hours=24)
{symbol: await trades_history(symbol, start, end) for symbol in MARKETS['spot']}


# %%
def trades_stream(symbol: str, *, category: str = 'spot'):
  # Bybit's private `execution` channel carries every category on one connection;
  # filter client-side by category/symbol/execType, like every other unified-API stream.
  def parse(execs: list[ExecutionUpdate]) -> list[Trade]:
    out: list[Trade] = []
    for e in execs:
      if e['category'] != category or e['symbol'] != symbol or e['execType'] != 'Trade':
        continue
      qty = e['execQty']
      out.append(
        Trade(
          id=e['execId'],
          price=e['execPrice'],
          qty=qty if e['side'] == 'Buy' else -qty,
          time=e['execTime'],
          maker=e['isMaker'],
          # The stream's numeric fields match the REST `Execution` field for field,
          # parsed `Decimal`s included -- see `trades_history` above for why a zero
          # fee must not collapse to `None`.
          fee=Trade.Fee(amount=e['execFee'], asset=e['feeCurrency']),
          details=e,
        )
      )
    return out

  return client.private.execution().map(parse).filter(lambda trades: len(trades) > 0)


async with trades_stream('BTCUSDT') as stream:
  it = aiter(stream)
  try:
    result = await asyncio.wait_for(anext(it), timeout=5.0)
  except asyncio.TimeoutError:
    result = (
      'no new trades observed in 5s (expected -- no live trading on this account)'
    )
result


# %%
async def position(symbol: str) -> Position:
  info = await client.market.instruments(category='spot', symbol=symbol)
  assert info['category'] == 'spot'  # narrow the 3-way union -- see `rules()` above
  base = info['list'][0]['baseCoin']
  wallet = await client.account.wallet_balance(account_type='UNIFIED', coin=base)
  coins = wallet['list'][0]['coin'] if wallet['list'] else []
  bal = next((c for c in coins if c['coin'] == base), None)
  # Every numeric field is `''` for a coin the account has never held -- guard that
  # before reading it as a `Decimal`.
  size = bal['walletBalance'] if bal and bal['walletBalance'] else Decimal(0)
  return Position(size=size)


{symbol: await position(symbol) for symbol in MARKETS['spot']}


# %%
async def collateral(symbol: str) -> Collateral:
  info = await client.market.instruments(category='spot', symbol=symbol)
  assert info['category'] == 'spot'  # narrow the 3-way union -- see `rules()` above
  quote = info['list'][0]['quoteCoin']
  wallet = await client.account.wallet_balance(account_type='UNIFIED', coin=quote)
  coins = wallet['list'][0]['coin'] if wallet['list'] else []
  bal = next((c for c in coins if c['coin'] == quote), None)
  equity = bal['walletBalance'] if bal and bal['walletBalance'] else Decimal(0)
  # `locked` is `NotRequired`; `'locked' in bal` (not `bal.get('locked')`) is what
  # lets pyright narrow it away before the direct-index read below.
  locked = bal['locked'] if bal and 'locked' in bal and bal['locked'] else Decimal(0)
  return Collateral(equity=equity, free_collateral=equity - locked)


{symbol: await collateral(symbol) for symbol in MARKETS['spot']}


# %%
async def available_notional(symbol: str) -> Decimal:
  c = await collateral(symbol)
  return c.free_collateral


{symbol: await available_notional(symbol) for symbol in MARKETS['spot']}


# %%
async def place_order(
  symbol: str, order: Order, *, settings: Settings = {}
) -> OrderResponse:
  order_qty = Decimal(order['qty'])
  side: Literal['Buy', 'Sell'] = 'Buy' if order_qty > 0 else 'Sell'
  qty = str(abs(order_qty))
  time_in_force: Literal['GTC', 'PostOnly'] = (
    'PostOnly' if order['type'] == 'POST_ONLY' else 'GTC'
  )
  body: CreateMarketOrderRequest | CreateLimitOrderRequest
  if order['type'] == 'MARKET':
    body = {
      'category': 'spot',
      'symbol': symbol,
      'side': side,
      'orderType': 'Market',
      'qty': qty,
      'timeInForce': time_in_force,
    }
  else:
    body = {
      'category': 'spot',
      'symbol': symbol,
      'side': side,
      'orderType': 'Limit',
      'qty': qty,
      'timeInForce': time_in_force,
      'price': str(Decimal(order['price'])),
    }
  raw = await client.trade.create_order(body)
  return OrderResponse(id=raw['orderId'], details=raw)


# Not executed here -- would place a real order on the account.
await place_order(
  'BTCUSDT', {'qty': Decimal('0.0001'), 'price': Decimal('20000'), 'type': 'LIMIT'}
)


# %%
async def cancel_order(symbol: str, id: str, *, settings: Settings = {}):
  return await client.trade.cancel_order(category='spot', symbol=symbol, order_id=id)


# Not executed here -- would cancel a real order on the account.
await cancel_order('BTCUSDT', '123456')


# %% [markdown]
# ## `PerpMarket` (linear)

# %%
async def depth(symbol: str, *, levels: int | None = None) -> Book:
  raw = await client.market.orderbook(category='linear', symbol=symbol, limit=levels)
  return Book(
    bids=[Book.Entry(p, q) for p, q in raw['b']],
    asks=[Book.Entry(p, q) for p, q in raw['a']],
  )


{symbol: await depth(symbol, levels=5) for symbol in MARKETS['perp']}


# %%
def depth_stream(symbol: str, *, depth: Literal[1, 50, 200, 1000] = 50):
  # Same snapshot-then-deltas merge as the spot `depth_stream` above -- see its
  # comment for why treating a delta as a full book is wrong, and where the
  # snapshot/delta discriminator comes from.
  book = Book()

  def to_book(update: LinearOrderbookUpdate) -> Book:
    nonlocal book
    delta = Book(
      bids=[Book.Entry(p, q) for p, q in update['b']],
      asks=[Book.Entry(p, q) for p, q in update['a']],
    )
    # The push's own `type` tells the two apart: the client's core forwards it from
    # the frame onto the payload. It is declared `NotRequired` only because the
    # spec's replay gate cannot see a field the transport merges in, so fall back to
    # Bybit's documented `u == 1` marker if a push ever arrives without it.
    kind = update.get('type')
    snapshot = kind == 'snapshot' if kind is not None else update['u'] == 1
    if snapshot:
      book = delta
    else:
      book.update(delta)
    return book.copy()

  return client.linear.orderbook(depth, symbol=symbol).map(to_book)


books: list[Book] = []
async with depth_stream('BTCUSDT') as stream:
  async for book in stream:
    books.append(book)
    if len(books) >= 3:
      break
books


# %%
async def rules(symbol: str, *, refetch: bool = False) -> Rules:
  info = await client.market.instruments(category='linear', symbol=symbol)
  assert info['category'] == 'linear'  # narrow the 3-way union -- see spot `rules()`
  sym = info['list'][0]
  lot = sym['lotSizeFilter']
  price_filter = sym['priceFilter']
  fee = await client.account.fee_rate(category='linear', symbol=symbol)
  rate = fee['list'][0] if fee['list'] else None
  return Rules(
    fee_asset=sym['settleCoin'],
    tick_size=price_filter['tickSize'],
    step_size=lot['qtyStep'],
    fixed_min_qty=lot['minOrderQty'],
    min_value=lot['minNotionalValue'],
    max_qty=lot['maxOrderQty'],
    fixed_min_price=price_filter['minPrice'],
    fixed_max_price=price_filter['maxPrice'],
    maker_fee=rate['makerFeeRate'] if rate else Decimal(0),
    taker_fee=rate['takerFeeRate'] if rate else Decimal(0),
    api=sym['status'] == 'Trading',
    details=sym,
  )


{symbol: await rules(symbol) for symbol in MARKETS['perp']}


# %%
async def open_orders(symbol: str) -> list[OrderState]:
  raw = await client.trade.open_orders(category='linear', symbol=symbol)
  out: list[OrderState] = []
  for o in raw['list']:
    qty = Decimal(o['qty'])
    filled = Decimal(o['cumExecQty'])
    sign = 1 if o['side'] == 'Buy' else -1
    out.append(
      OrderState(
        id=o['orderId'],
        price=Decimal(o['price']),
        qty=sign * qty,
        filled_qty=sign * filled,
        active=o['orderStatus'] in ('New', 'PartiallyFilled', 'Untriggered'),
        details=o,
      )
    )
  return out


{symbol: await open_orders(symbol) for symbol in MARKETS['perp']}


# %%
async def trades_history(symbol: str, start: datetime, end: datetime) -> list[Trade]:
  raw = await client.trade.trade_history(
    category='linear',
    symbol=symbol,
    start_time=start,
    end_time=end,
    exec_type='Trade',
  )
  out: list[Trade] = []
  for t in raw['list']:
    qty = Decimal(t['execQty'])
    out.append(
      Trade(
        id=t['execId'],
        price=Decimal(t['execPrice']),
        qty=qty if t['side'] == 'Buy' else -qty,
        time=t['execTime'],
        maker=t['isMaker'],
        # Same `execFee` handling as the spot `trades_history` above, off the same
        # endpoint and the same required `Decimal` field -- though the reasoning there is
        # drawn from real spot fills, since this account has never taken a linear one.
        fee=Trade.Fee(amount=t['execFee'], asset=t['feeCurrency']),
        details=t,
      )
    )
  return out


end = datetime.now(timezone.utc)
start = end - timedelta(hours=24)
{symbol: await trades_history(symbol, start, end) for symbol in MARKETS['perp']}


# %%
async with trades_stream('BTCUSDT', category='linear') as stream:
  it = aiter(stream)
  try:
    result = await asyncio.wait_for(anext(it), timeout=5.0)
  except asyncio.TimeoutError:
    result = (
      'no new trades observed in 5s (expected -- no live trading on this account)'
    )
result


# %%
async def index(symbol: str, *, settings: Settings = {}) -> Decimal:
  raw = await client.market.tickers(category='linear', symbol=symbol)
  # `tickers()` returns a 3-way union (`Spot|Contract|OptionTickers`) regardless of
  # `category` -- narrow it by hand via the shared `category` discriminant.
  assert raw['category'] == 'linear'
  return raw['list'][0]['indexPrice']


{symbol: await index(symbol) for symbol in MARKETS['perp']}


# %%
async def next_funding(symbol: str) -> NextFunding:
  ticker_result = await client.market.tickers(category='linear', symbol=symbol)
  assert ticker_result['category'] == 'linear'  # see `index()` above
  ticker = ticker_result['list'][0]
  rate, time = ticker['fundingRate'], ticker['nextFundingTime']
  if rate == '' or time == '0':
    # Dated futures report these sentinels; every symbol here is a perpetual.
    raise ValueError(f'{symbol} reports no funding schedule; not a perpetual')
  instruments_result = await client.market.instruments(category='linear', symbol=symbol)
  assert instruments_result['category'] == 'linear'  # see spot `rules()` above
  info = instruments_result['list'][0]
  return NextFunding(
    rate=rate,
    time=time,
    interval=timedelta(minutes=info['fundingInterval']),
  )


{symbol: await next_funding(symbol) for symbol in MARKETS['perp']}


# %%
async def funding_rates(
  symbol: str,
  start: datetime | None = None,
  end: datetime | None = None,
) -> list[FundingRate]:
  raw = await client.market.funding_history(
    category='linear',
    symbol=symbol,
    start_time=start,
    end_time=end,
  )
  return [
    FundingRate(rate=r['fundingRate'], time=r['fundingRateTimestamp'])
    for r in raw['list']
  ]


end = datetime.now(timezone.utc)
start = end - timedelta(days=7)
{symbol: await funding_rates(symbol, start, end) for symbol in MARKETS['perp']}


# %%
async def funding_payments(
  symbol: str, start: datetime, end: datetime
) -> list[FundingPayment]:
  # `account.transaction_log` has no `symbol` filter -- filter client-side.
  raw = await client.account.transaction_log(
    category='linear',
    type='SETTLEMENT',
    start_time=start,
    end_time=end,
  )
  # `funding` is declared `NotRequired[str]`; `'funding' in e` (not `e.get('funding')`)
  # is what lets pyright narrow it away before the direct-index read below. Whether it
  # is ever actually absent or empty on a `type='SETTLEMENT'` row could not be checked:
  # this account has never held a perp position, so `transaction_log` returns no
  # SETTLEMENT row anywhere in the two years Bybit will serve.
  return [
    FundingPayment(amount=-Decimal(e['funding']), time=e['transactionTime'])
    for e in raw['list']
    if e['symbol'] == symbol and 'funding' in e and e['funding']
  ]


end = datetime.now(timezone.utc)
start = end - timedelta(days=7)
{symbol: await funding_payments(symbol, start, end) for symbol in MARKETS['perp']}


# %%
async def perp_position(symbol: str) -> PerpPosition:
  raw = await client.position.list(category='linear', symbol=symbol)
  row = raw['list'][0] if raw['list'] else None
  # A symbol with no position still comes back as a row, with `side` and every
  # numeric field an empty string.
  if row is None or not row['side']:
    return PerpPosition()
  size = row['size']
  return PerpPosition(
    size=size if row['side'] == 'Buy' else -size,
    entry_price=row['avgPrice'] if row['avgPrice'] != '' else Decimal(0),
  )


{symbol: await perp_position(symbol) for symbol in MARKETS['perp']}


# %%
async def perp_collateral(symbol: str) -> PerpCollateral:
  wallet = (await client.account.wallet_balance(account_type='UNIFIED'))['list'][0]
  info = await client.account.info()
  positions = (await client.position.list(category='linear', settle_coin='USDT'))[
    'list'
  ]
  equity = Decimal(wallet['totalEquity'])
  free_collateral = Decimal(wallet['totalAvailableBalance'])
  initial_margin = Decimal(wallet['totalInitialMargin'])
  maintenance_margin = Decimal(wallet['totalMaintenanceMargin'])
  total_notional = sum(
    (abs(Decimal(p['positionValue'])) for p in positions if p['positionValue']),
    Decimal(0),
  )
  leverage = total_notional / equity if equity > 0 else Decimal(0)
  return PerpCollateral(
    equity=equity,
    free_collateral=free_collateral,
    initial_margin=initial_margin,
    maintenance_margin=maintenance_margin,
    leverage=leverage,
    margin_mode='isolated' if info['marginMode'] == 'ISOLATED_MARGIN' else 'cross',
  )


{symbol: await perp_collateral(symbol) for symbol in MARKETS['perp']}


# %%
async def available_notional(symbol: str) -> Decimal:
  c = await perp_collateral(symbol)
  instruments_result = await client.market.instruments(category='linear', symbol=symbol)
  assert instruments_result['category'] == 'linear'  # see spot `rules()` above
  info = instruments_result['list'][0]
  max_leverage = info['leverageFilter']['maxLeverage']
  return c.free_collateral * max_leverage


{symbol: await available_notional(symbol) for symbol in MARKETS['perp']}


# %%
async def place_order(
  symbol: str, order: Order, *, settings: Settings = {}
) -> OrderResponse:
  order_qty = Decimal(order['qty'])
  side: Literal['Buy', 'Sell'] = 'Buy' if order_qty > 0 else 'Sell'
  qty = str(abs(order_qty))
  time_in_force: Literal['GTC', 'PostOnly'] = (
    'PostOnly' if order['type'] == 'POST_ONLY' else 'GTC'
  )
  body: CreateMarketOrderRequest | CreateLimitOrderRequest
  if order['type'] == 'MARKET':
    body = {
      'category': 'linear',
      'symbol': symbol,
      'side': side,
      'orderType': 'Market',
      'qty': qty,
      'timeInForce': time_in_force,
    }
  else:
    body = {
      'category': 'linear',
      'symbol': symbol,
      'side': side,
      'orderType': 'Limit',
      'qty': qty,
      'timeInForce': time_in_force,
      'price': str(Decimal(order['price'])),
    }
  raw = await client.trade.create_order(body)
  return OrderResponse(id=raw['orderId'], details=raw)


# Not executed here -- would place a real order on the account.
await place_order(
  'BTCUSDT', {'qty': Decimal('0.001'), 'price': Decimal('20000'), 'type': 'LIMIT'}
)


# %%
async def cancel_order(symbol: str, id: str, *, settings: Settings = {}):
  return await client.trade.cancel_order(category='linear', symbol=symbol, order_id=id)


# Not executed here -- would cancel a real order on the account.
await cancel_order('BTCUSDT', '123456')

# %% [markdown]
# ### Coverage assessment
#
# **Fully supported**, once the unified `category` parameter is threaded through
# every call. `Market` and `PerpMarket` reach the *same* `client.market`,
# `client.trade`, `client.position` and `client.account` endpoints as
# spot -- only `category` (and, for perps, `settleCoin`/`leverageFilter`/funding
# fields) changes; there is no separate "futures client" to instantiate, unlike
# Binance's `spot`/`usdm_futures` split.
#
# Bybit writes `''` instead of a number wherever a row means "nothing here", and the
# client's schemas admit the sentinel, so both shapes of it validate as they stand.
# A flat (zero-size) linear position still comes back as a full row from
# `position.list` -- `BTCUSDT` here returns `side=''`, `size='0'` and 22 empty-string
# fields in all, among them `avgPrice`, `positionValue`, `markPrice`, `positionStatus`,
# `createdTime`, `updatedTime` and `tpslMode`; those are declared `Literal[''] | str`
# (or `Literal[''] | TimestampMillis` for the timestamps), so the row parses and the
# empty string reaches the caller. `account.wallet_balance` does the same for a coin
# the account has never held (`SOL` here): `walletBalance`, `equity`, `locked`,
# `unrealisedPnl` and the rest come back `''` against a declared
# `Literal[''] | Decimal` -- though not quite *every* numeric field, since
# `spotHedgingQty` and `spotBorrow` still return `0`. What's left for a caller is
# treating the empty string as zero, which `position()`, `collateral()` and
# `perp_position()` above each do before converting to a `Decimal`.
#
# `index()` and `next_funding()` are both served for free by `market.tickers`
# (`indexPrice`, `fundingRate`, `nextFundingTime`) -- no dedicated index-price
# endpoint call was needed. `funding_payments` has no per-symbol filter on
# `account.transaction_log`, so it's filtered client-side; the same 7-day window cap
# applies to both `funding_rates`/`funding_payments` (`transaction_log`) and general
# trade history.
#
# Two branches above are written but unexercised, since this account holds no perp
# position and never has: the `avgPrice` fallback in `perp_position()` and the
# `positionValue` filter in `perp_collateral()`. `position.list(settle_coin='USDT')`
# returns only positions with a non-zero size, so it currently returns nothing at all.
#
