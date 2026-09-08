# %%
import asyncio
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from typing_extensions import AsyncIterator, Literal

from typed_binance import Binance
from typed_binance.spot import streams
from typed_binance.spot.ws.user_data.events import UserDataPush
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

client = Binance.new()

MARKETS = {
  'spot': ['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
  'perp': ['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
}


# %% [markdown]
# ## `Market` (spot)

# %%
async def depth(symbol: str, *, levels: int | None = None) -> Book:
  raw = await client.spot.http.market.order_book(symbol=symbol, limit=levels)
  return Book(
    bids=[Book.Entry(price, qty) for price, qty in raw['bids']],
    asks=[Book.Entry(price, qty) for price, qty in raw['asks']],
  )


{symbol: await depth(symbol, levels=5) for symbol in MARKETS['spot']}


# %%
def depth_stream(symbol: str, *, levels: Literal[5, 10, 20] = 5):
  def to_book(event: streams.partial_depth.PartialDepthEvent) -> Book:
    return Book(
      bids=[Book.Entry(price, qty) for price, qty in event['bids']],
      asks=[Book.Entry(price, qty) for price, qty in event['asks']],
    )

  return client.spot.streams.partial_depth(symbol, levels=levels).map(to_book)


books: list[Book] = []
async with depth_stream('BTCUSDT'.lower()) as stream:
  print(stream.reply)
  async for book in stream:
    print(book.best_bid, book.best_ask)
    books.append(book)
    if len(books) >= 3:
      break


# %%
async def rules(symbol: str, *, refetch: bool = False) -> Rules:
  info = await client.spot.http.market.exchange_info(symbol=symbol)
  sym = info['symbols'][0]
  price_filter = next(
    (f for f in sym['filters'] if f['filterType'] == 'PRICE_FILTER'), None
  )
  lot_size = next((f for f in sym['filters'] if f['filterType'] == 'LOT_SIZE'), None)
  notional = next(
    (f for f in sym['filters'] if f['filterType'] == 'NOTIONAL'), None
  ) or next((f for f in sym['filters'] if f['filterType'] == 'MIN_NOTIONAL'), None)
  account = await client.spot.http.account.info()
  commission = account['commissionRates']
  return Rules(
    base=sym['baseAsset'],
    quote=sym['quoteAsset'],
    fee_asset=sym['quoteAsset'],
    tick_size=price_filter['tickSize'] if price_filter else Decimal(0),
    step_size=lot_size['stepSize'] if lot_size else Decimal(0),
    fixed_min_qty=lot_size['minQty'] if lot_size else None,
    min_value=notional['minNotional'] if notional else None,
    max_qty=lot_size['maxQty'] if lot_size else None,
    maker_fee=commission['maker'],
    taker_fee=commission['taker'],
    api=sym['isSpotTradingAllowed'],
    details=sym,
  )


{symbol: await rules(symbol) for symbol in MARKETS['spot']}


# %%
async def open_orders(symbol: str) -> list[OrderState]:
  raw = await client.spot.http.account.open_orders(symbol=symbol)
  out: list[OrderState] = []
  for o in raw:
    orig_qty = Decimal(o['origQty'])
    executed_qty = Decimal(o['executedQty'])
    sign = 1 if o['side'] == 'BUY' else -1
    out.append(
      OrderState(
        id=str(o['orderId']),
        price=Decimal(o['price']),
        qty=sign * orig_qty,
        filled_qty=sign * executed_qty,
        active=o['status'] in ('NEW', 'PARTIALLY_FILLED'),
        details=o,
      )
    )
  return out


{symbol: await open_orders(symbol) for symbol in MARKETS['spot']}


# %%
async def trades_history(symbol: str, start: datetime, end: datetime) -> list[Trade]:
  raw = await client.spot.http.account.my_trades(
    symbol=symbol, start_time=start, end_time=end
  )
  return [
    Trade(
      id=str(t['id']),
      price=t['price'],
      qty=t['qty'] if t['isBuyer'] else -t['qty'],
      time=t['time'],
      maker=t['isMaker'],
      fee=Trade.Fee(amount=t['commission'], asset=t['commissionAsset']),
      details=t,
    )
    for t in raw
  ]


end = datetime.now(timezone.utc)
start = end - timedelta(hours=24)
{symbol: await trades_history(symbol, start, end) for symbol in MARKETS['spot']}


# %%
def trades_stream(symbol: str):
  # Spot's user-data push isn't a listenKey market-stream (unlike futures) -- it's a
  # signed `userDataStream.subscribe` upgrade of the WS API connection itself.
  def parse(push: UserDataPush) -> Trade | None:
    event = push['event']
    if event['e'] != 'executionReport' or event['x'] != 'TRADE':
      return None
    if event['s'] != symbol:
      return None
    qty = event['l']
    return Trade(
      id=str(event['t']),
      price=event['L'],
      qty=qty if event['S'] == 'BUY' else -qty,
      time=event['T'],
      maker=event['m'],
      # `N` is null when no commission was charged -- the only nullable half of the pair.
      fee=Trade.Fee(amount=event['n'], asset=event['N'])
      if event['N'] is not None
      else None,
      details=event,
    )

  return client.spot.ws.user_data.events().map(parse).filter(lambda t: t is not None)


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
  info = await client.spot.http.market.exchange_info(symbol=symbol)
  base = info['symbols'][0]['baseAsset']
  account = await client.spot.http.account.info()
  balance = next((b for b in account['balances'] if b['asset'] == base), None)
  size = (balance['free'] + balance['locked']) if balance else Decimal(0)
  return Position(size=size)


{symbol: await position(symbol) for symbol in MARKETS['spot']}


# %%
async def collateral(symbol: str) -> Collateral:
  info = await client.spot.http.market.exchange_info(symbol=symbol)
  quote = info['symbols'][0]['quoteAsset']
  account = await client.spot.http.account.info()
  balance = next((b for b in account['balances'] if b['asset'] == quote), None)
  free = balance['free'] if balance else Decimal(0)
  locked = balance['locked'] if balance else Decimal(0)
  return Collateral(equity=free + locked, free_collateral=free)


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
  qty = Decimal(order['qty'])
  side: Literal['BUY', 'SELL'] = 'BUY' if qty > 0 else 'SELL'
  quantity = str(abs(qty))
  price = str(Decimal(order['price']))
  if order['type'] == 'MARKET':
    raw = await client.spot.http.trading.order(
      {'symbol': symbol, 'side': side, 'type': 'MARKET', 'quantity': quantity}
    )
  elif order['type'] == 'POST_ONLY':
    raw = await client.spot.http.trading.order(
      {
        'symbol': symbol,
        'side': side,
        'type': 'LIMIT_MAKER',
        'quantity': quantity,
        'price': price,
      }
    )
  else:
    raw = await client.spot.http.trading.order(
      {
        'symbol': symbol,
        'side': side,
        'type': 'LIMIT',
        'timeInForce': 'GTC',
        'quantity': quantity,
        'price': price,
      }
    )
  return OrderResponse(id=str(raw['orderId']), details=raw)


# Not executed here -- would place a real order on the account.
await place_order(
  'BTCUSDT', {'qty': Decimal('0.0001'), 'price': Decimal('20000'), 'type': 'LIMIT'}
)


# %%
async def cancel_order(symbol: str, id: str, *, settings: Settings = {}):
  return await client.spot.http.trading.cancel_order(symbol=symbol, order_id=int(id))


# Not executed here -- would cancel a real order on the account.
await cancel_order('BTCUSDT', '123456')


# %% [markdown]
# ## `PerpMarket` (USD-M futures)
#
# The public endpoints below (`depth`, `depth_stream`, `index`, `next_funding`,
# `funding_rates`) return live data. Every *signed* USD-M call raises
# `AuthError(401, -2015)` on this account: the API key in `.env` has `enableFutures:
# false` (confirmed by `spot.http.wallet.account.api_restrictions()` in
# `reporting.ipynb`) and the account is geo-blocked from enabling it, so those cells
# are written but left unexecuted (`not attempted`): the mapping is unverified.
#

# %%
async def depth(
  symbol: str, *, levels: Literal[5, 10, 20, 50, 100, 500, 1000] | None = None
) -> Book:
  raw = await client.usdm_futures.http.market.depth(symbol=symbol, limit=levels)
  return Book(
    bids=[Book.Entry(price, qty) for price, qty in raw['bids']],
    asks=[Book.Entry(price, qty) for price, qty in raw['asks']],
  )


{symbol: await depth(symbol, levels=5) for symbol in MARKETS['perp']}

# %%
from typed_binance.usdm_futures import public_streams


def depth_stream(
  symbol: str, *, levels: Literal[5, 10, 20] = 5, speed: Literal[100, 250, 500] = 100
):
  def to_book(event: public_streams.partial_depth.PartialDepthEvent) -> Book:
    return Book(
      bids=[Book.Entry(Decimal(p), Decimal(q)) for p, q in event['b']],
      asks=[Book.Entry(Decimal(p), Decimal(q)) for p, q in event['a']],
    )

  return client.usdm_futures.public_streams.partial_depth(
    symbol, levels=levels, speed=speed
  ).map(to_book)


books: list[Book] = []
async with depth_stream('BTCUSDT'.lower()) as stream:
  print(stream.reply)
  async for book in stream:
    print(book.best_bid, book.best_ask)
    books.append(book)
    if len(books) >= 3:
      break
books


# %%
async def rules(symbol: str, *, refetch: bool = False) -> Rules:
  info = await client.usdm_futures.http.market.exchange_info()
  sym = next(s for s in info['symbols'] if s['symbol'] == symbol)
  filters = {f['filterType']: f for f in sym['filters']}
  price_filter = filters.get('PRICE_FILTER')
  lot_size = filters.get('LOT_SIZE')
  min_notional = filters.get('MIN_NOTIONAL')
  fee = await client.usdm_futures.http.trading.trading_fee(symbol=symbol)
  return Rules(
    base=sym['baseAsset'],
    quote=sym['quoteAsset'],
    fee_asset=sym['marginAsset'],
    tick_size=(price_filter.get('tickSize') if price_filter else None) or Decimal(0),
    step_size=(lot_size.get('stepSize') if lot_size else None) or Decimal(0),
    fixed_min_qty=lot_size.get('minQty') if lot_size else None,
    min_value=min_notional.get('notional') if min_notional else None,
    max_qty=lot_size.get('maxQty') if lot_size else None,
    maker_fee=Decimal(v) if (v := fee.get('makerCommissionRate')) else Decimal(0),
    taker_fee=Decimal(v) if (v := fee.get('takerCommissionRate')) else Decimal(0),
    api=sym['status'] == 'TRADING',
    details=sym,
  )


# not executed: signed USD-M futures calls 401 on this key (`enableFutures` is false, see `api_restrictions()` in reporting.ipynb, and the account is geo-blocked from enabling it)
{symbol: await rules(symbol) for symbol in MARKETS['perp']}


# %%
async def open_orders(symbol: str) -> list[OrderState]:
  raw = await client.usdm_futures.http.trading.open_orders(symbol=symbol)
  out: list[OrderState] = []
  for o in raw:
    orig_qty = Decimal(o['origQty'])
    executed_qty = Decimal(o['executedQty'])
    sign = 1 if o['side'] == 'BUY' else -1
    out.append(
      OrderState(
        id=str(o['orderId']),
        price=Decimal(o['price']),
        qty=sign * orig_qty,
        filled_qty=sign * executed_qty,
        active=o['status'] in ('NEW', 'PARTIALLY_FILLED'),
        details=o,
      )
    )
  return out


# not executed: signed USD-M futures calls 401 on this key (`enableFutures` is false, see `api_restrictions()` in reporting.ipynb, and the account is geo-blocked from enabling it)
{symbol: await open_orders(symbol) for symbol in MARKETS['perp']}


# %%
async def trades_history(symbol: str, start: datetime, end: datetime) -> list[Trade]:
  raw = await client.usdm_futures.http.trading.user_trades(
    symbol=symbol, start_time=start, end_time=end
  )
  return [
    Trade(
      id=str(t['id']),
      price=Decimal(t['price']),
      qty=Decimal(t['qty']) if t.get('side') == 'BUY' else -Decimal(t['qty']),
      time=t['time'],
      maker=bool(t.get('maker')),
      fee=Trade.Fee(amount=Decimal(t['commission']), asset=t['commissionAsset'])
      if 'commission' in t and 'commissionAsset' in t
      else None,
      details=t,
    )
    for t in raw
    if 'id' in t and 'price' in t and 'qty' in t and 'time' in t
  ]


# not executed: signed USD-M futures calls 401 on this key (`enableFutures` is false, see `api_restrictions()` in reporting.ipynb, and the account is geo-blocked from enabling it)
end = datetime.now(timezone.utc)
start = end - timedelta(hours=24)
{symbol: await trades_history(symbol, start, end) for symbol in MARKETS['perp']}


# %%
async def trades_stream(symbol: str) -> AsyncIterator[Trade]:
  session = await client.usdm_futures.http.account.listen_key_start()
  listen_key = session.get('listenKey')
  if listen_key is None:
    raise RuntimeError('listen_key_start did not return a listenKey')
  async with client.usdm_futures.private_streams.user_data(listen_key) as stream:
    async for event in stream:
      if event['e'] != 'ORDER_TRADE_UPDATE':
        continue
      o = event['o']
      if o.get('x') != 'TRADE':
        continue
      # The fill fields are NotRequired on `OrderUpdateDetail`: they're absent on the
      # non-TRADE execution types this event also carries, so guard rather than index.
      qty = o.get('l')
      price = o.get('L')
      trade_id = o.get('t')
      if qty is None or price is None or trade_id is None:
        continue
      fee_amount = o.get('n')
      fee_asset = o.get('N')
      yield Trade(
        id=str(trade_id),
        price=price,
        qty=qty if o['S'] == 'BUY' else -qty,
        time=event['E'],
        maker=bool(o.get('m')),
        fee=Trade.Fee(amount=fee_amount, asset=fee_asset)
        if fee_amount is not None and fee_asset is not None
        else None,
        details=o,
      )


# not executed: signed USD-M futures calls 401 on this key (`enableFutures` is false, see `api_restrictions()` in reporting.ipynb, and the account is geo-blocked from enabling it)
stream = trades_stream('BTCUSDT')
try:
  result = await asyncio.wait_for(anext(stream), timeout=5.0)
except asyncio.TimeoutError:
  result = 'no new trades observed in 5s'
except Exception as e:
  result = f'{type(e).__name__}: {e}'
result


# %%
async def index(symbol: str, *, settings: Settings = {}) -> Decimal:
  raw = await client.usdm_futures.http.market.premium_index(symbol=symbol)
  info = raw[0] if isinstance(raw, list) else raw
  return info['indexPrice']


{symbol: await index(symbol) for symbol in MARKETS['perp']}


# %%
async def next_funding(symbol: str) -> NextFunding:
  raw = await client.usdm_futures.http.market.premium_index(symbol=symbol)
  premium = raw[0] if isinstance(raw, list) else raw
  info = await client.usdm_futures.http.market.funding_info()
  cfg = next((f for f in info if f['symbol'] == symbol), None)
  interval_hours = cfg['fundingIntervalHours'] if cfg else 8
  return NextFunding(
    rate=premium['lastFundingRate'],
    time=premium['nextFundingTime'],
    interval=timedelta(hours=interval_hours),
  )


{symbol: await next_funding(symbol) for symbol in MARKETS['perp']}


# %%
async def funding_rates(
  symbol: str,
  start: datetime | None = None,
  end: datetime | None = None,
) -> list[FundingRate]:
  raw = await client.usdm_futures.http.market.funding_rate(
    symbol=symbol, start_time=start, end_time=end
  )
  return [FundingRate(rate=r['fundingRate'], time=r['fundingTime']) for r in raw]


end = datetime.now(timezone.utc)
start = end - timedelta(days=7)
{symbol: await funding_rates(symbol, start, end) for symbol in MARKETS['perp']}


# %%
async def funding_payments(
  symbol: str, start: datetime, end: datetime
) -> list[FundingPayment]:
  raw = await client.usdm_futures.http.account.income(
    symbol=symbol,
    income_type='FUNDING_FEE',
    start_time=start,
    end_time=end,
  )
  return [
    FundingPayment(amount=-Decimal(i['income']), time=i['time'])
    for i in raw
    if 'income' in i and 'time' in i
  ]


# not executed: signed USD-M futures calls 401 on this key (`enableFutures` is false, see `api_restrictions()` in reporting.ipynb, and the account is geo-blocked from enabling it)
end = datetime.now(timezone.utc)
start = end - timedelta(days=7)
{symbol: await funding_payments(symbol, start, end) for symbol in MARKETS['perp']}


# %%
async def perp_position(symbol: str) -> PerpPosition:
  raw = await client.usdm_futures.http.trading.position_risk_v3(symbol=symbol)
  row = next((r for r in raw if r['positionSide'] == 'BOTH'), raw[0] if raw else None)
  if row is None:
    return PerpPosition()
  return PerpPosition(
    size=Decimal(row['positionAmt']),
    entry_price=Decimal(row.get('entryPrice') or '0'),
  )


# not executed: signed USD-M futures calls 401 on this key (`enableFutures` is false, see `api_restrictions()` in reporting.ipynb, and the account is geo-blocked from enabling it)
{symbol: await perp_position(symbol) for symbol in MARKETS['perp']}


# %%
async def perp_collateral(symbol: str) -> PerpCollateral:
  account = await client.usdm_futures.http.account.account_v3()
  positions = account.get('positions') or []
  assets = account.get('assets') or []
  usdt = next((a for a in assets if a.get('asset') == 'USDT'), None)
  equity = (
    Decimal(usdt['marginBalance']) if usdt and 'marginBalance' in usdt else Decimal(0)
  )
  free_collateral = (
    Decimal(usdt['availableBalance'])
    if usdt and 'availableBalance' in usdt
    else Decimal(0)
  )
  initial_margin = (
    Decimal(account['totalInitialMargin'])
    if 'totalInitialMargin' in account
    else Decimal(0)
  )
  maintenance_margin = (
    Decimal(account['totalMaintMargin'])
    if 'totalMaintMargin' in account
    else Decimal(0)
  )
  total_notional = sum(
    (abs(Decimal(p['notional'])) for p in positions if 'notional' in p), Decimal(0)
  )
  leverage = total_notional / equity if equity > 0 else Decimal(0)
  sym_position = next((p for p in positions if p.get('symbol') == symbol), None)
  is_isolated = bool(
    sym_position and Decimal(sym_position.get('isolatedMargin') or '0') != 0
  )
  return PerpCollateral(
    equity=equity,
    free_collateral=free_collateral,
    initial_margin=initial_margin,
    maintenance_margin=maintenance_margin,
    leverage=leverage,
    margin_mode='isolated' if is_isolated else 'cross',
  )


# not executed: signed USD-M futures calls 401 on this key (`enableFutures` is false, see `api_restrictions()` in reporting.ipynb, and the account is geo-blocked from enabling it)
{symbol: await perp_collateral(symbol) for symbol in MARKETS['perp']}


# %%
async def available_notional(symbol: str) -> Decimal:
  c = await perp_collateral(symbol)
  raw = await client.usdm_futures.http.account.leverage_bracket(symbol=symbol)
  group = (raw[0] if raw else None) if isinstance(raw, list) else raw
  rows = group.get('brackets') if group else None
  max_leverage = rows[0].get('initialLeverage') if rows else None
  return c.free_collateral * (max_leverage or 1)


# not executed: signed USD-M futures calls 401 on this key (`enableFutures` is false, see `api_restrictions()` in reporting.ipynb, and the account is geo-blocked from enabling it)
{symbol: await available_notional(symbol) for symbol in MARKETS['perp']}


# %%
async def place_order(
  symbol: str, order: Order, *, settings: Settings = {}
) -> OrderResponse:
  qty = Decimal(order['qty'])
  side: Literal['BUY', 'SELL'] = 'BUY' if qty > 0 else 'SELL'
  quantity = str(abs(qty))
  price = str(Decimal(order['price']))
  if order['type'] == 'MARKET':
    raw = await client.usdm_futures.http.trading.new_order(
      {'symbol': symbol, 'side': side, 'type': 'MARKET', 'quantity': quantity}
    )
  else:
    time_in_force: Literal['GTX', 'GTC'] = (
      'GTX' if order['type'] == 'POST_ONLY' else 'GTC'
    )
    raw = await client.usdm_futures.http.trading.new_order(
      {
        'symbol': symbol,
        'side': side,
        'type': 'LIMIT',
        'timeInForce': time_in_force,
        'quantity': quantity,
        'price': price,
      }
    )
  return OrderResponse(id=str(raw['orderId']), details=raw)


# Not executed here -- would place a real order on the account.
await place_order(
  'BTCUSDT', {'qty': Decimal('0.001'), 'price': Decimal('20000'), 'type': 'LIMIT'}
)


# %%
async def cancel_order(symbol: str, id: str, *, settings: Settings = {}):
  return await client.usdm_futures.http.trading.cancel_order(
    symbol=symbol, order_id=int(id)
  )


# Not executed here -- would cancel a real order on the account.
await cancel_order('BTCUSDT', '123456')
