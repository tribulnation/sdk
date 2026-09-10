# %%
import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os

from typing_extensions import Literal

from dotenv import load_dotenv

from typed_mexc import MEXC
from typed_mexc.core import ApiError, timestamp_millis as ts
from typed_mexc.futures.http.trade.submit_order import IsolatedMarginOrder
from typed_mexc.futures.streams.market.depth import DepthPushMessage
from typed_mexc.futures.streams.user.my_trades import OrderDealPushMessage
from typed_mexc.spot.http.trade.place_order import (
  LimitOrderRequest,
  MarketOrderByQuantityRequest,
)
from typed_mexc.spot.streams.core.proto import (
  PrivateDealsV3Api,
  PublicLimitDepthsV3Api,
)

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
  Trade,
)

load_dotenv()

client = await MEXC.new(
  api_key=os.environ['MEXC_API_KEY'],
  api_secret=os.environ['MEXC_API_SECRET'],
).__aenter__()

MARKETS = {
  'spot': ['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
  'perp': ['BTC_USDT', 'ETH_USDT', 'SOL_USDT'],
}


# %% [markdown]
# ## `Market` (spot)

# %%
async def depth(symbol: str, *, levels: int | None = None) -> Book:
  raw = await client.spot.http.market.depth(symbol=symbol, limit=levels)
  return Book(
    bids=[Book.Entry(Decimal(p), Decimal(q)) for p, q in raw['bids']],
    asks=[Book.Entry(Decimal(p), Decimal(q)) for p, q in raw['asks']],
  )


{symbol: await depth(symbol, levels=5) for symbol in MARKETS['spot']}


# %%
def depth_stream(symbol: str, *, levels: Literal[5, 10, 20] = 5):
  def to_book(msg: PublicLimitDepthsV3Api) -> Book:
    return Book(
      bids=[Book.Entry(Decimal(e.price), Decimal(e.quantity)) for e in msg.bids],
      asks=[Book.Entry(Decimal(e.price), Decimal(e.quantity)) for e in msg.asks],
    )

  return client.spot.streams.market.depth(symbol, levels).map(to_book)


books: list[Book] = []
async with depth_stream('BTCUSDT') as stream:
  async for book in stream:
    books.append(book)
    if len(books) >= 3:
      break
books


# %%
async def rules(symbol: str) -> Rules:
  info = await client.spot.http.market.exchange_info(symbol=symbol)
  sym = info['symbols'][0]
  fee = await client.spot.http.account.trade_fee(symbol=symbol)
  # MEXC's exchange_info carries no PRICE_FILTER/LOT_SIZE-style filters (its one spot
  # filter is PERCENT_PRICE_BY_SIDE) -- tick/step size are instead derived from the
  # quote/base precision and quantity-precision fields it does report.
  base_size_precision = sym.get('baseSizePrecision')
  return Rules(
    fee_asset=sym['quoteAsset'],
    tick_size=Decimal(1).scaleb(-sym['quoteAssetPrecision']),
    step_size=Decimal(str(base_size_precision))
    if base_size_precision
    else Decimal(1).scaleb(-sym['baseAssetPrecision']),
    maker_fee=Decimal(str(fee['data']['makerCommission'])),
    taker_fee=Decimal(str(fee['data']['takerCommission'])),
    api=sym['isSpotTradingAllowed'],
    details=sym,
  )


{symbol: await rules(symbol) for symbol in MARKETS['spot']}


# %% [markdown]
# `open_orders`/`trades_history` fail live with the same MEXC error -- this API key
# doesn't have the scope for these account-sensitive spot endpoints, confirmed by the
# response code, not a code issue:

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


try:
  open_orders_result = {symbol: await open_orders(symbol) for symbol in MARKETS['spot']}
except ApiError as e:
  open_orders_result = e
open_orders_result


# %%
async def trades_history(symbol: str, start: datetime, end: datetime) -> list[Trade]:
  raw = await client.spot.http.account.trades(
    symbol=symbol, start_time=start, end_time=end
  )
  return [
    Trade(
      id=str(t['id']),
      price=Decimal(t['price']),
      qty=Decimal(t['qty']) if t['isBuyer'] else -Decimal(t['qty']),
      time=t['time'],
      maker=t['isMaker'],
      fee=Trade.Fee(amount=Decimal(t['commission']), asset=t['commissionAsset'])
      if Decimal(t['commission'])
      else None,
      details=t,
    )
    for t in raw
  ]


end = datetime.now(timezone.utc)
start = end - timedelta(hours=24)
try:
  trades_history_result = {
    symbol: await trades_history(symbol, start, end) for symbol in MARKETS['spot']
  }
except ApiError as e:
  trades_history_result = e
trades_history_result


# %% [markdown]
# `trades_stream` (the account's own private fills feed) doesn't need the same scope and
# works live -- it simply observes no fills in the window. Note MEXC's private-deals push
# (`spot@private.deals.v3.api.pb`) carries no symbol field (unlike the order-update push,
# which has `market`), so unlike other venues this can't be filtered by symbol at all --
# it's account-wide by construction:

# %%
def trades_stream():
  def to_trade(d: PrivateDealsV3Api) -> Trade:
    qty = Decimal(d.quantity)
    side = 'BUY' if d.trade_type == 1 else 'SELL'
    return Trade(
      id=d.trade_id,
      price=Decimal(d.price),
      qty=qty if side == 'BUY' else -qty,
      time=ts.parse(d.time),
      maker=d.is_maker,
      fee=Trade.Fee(amount=Decimal(d.fee_amount), asset=d.fee_currency)
      if d.fee_amount
      else None,
      details=d,
    )

  return client.spot.streams.user.trades().map(to_trade)


async with trades_stream() as stream:
  it = aiter(stream)
  try:
    trade = await asyncio.wait_for(anext(it), timeout=5.0)
  except asyncio.TimeoutError:
    trade = 'no new trades observed in 5s (expected -- no live trading on this account)'
trade


# %%
async def position(symbol: str) -> Position:
  info = await client.spot.http.market.exchange_info(symbol=symbol)
  base = info['symbols'][0]['baseAsset']
  account = await client.spot.http.account.info()
  balance = next((b for b in account['balances'] if b['asset'] == base), None)
  size = (
    (Decimal(balance['free']) + Decimal(balance['locked'])) if balance else Decimal(0)
  )
  return Position(size=size)


{symbol: await position(symbol) for symbol in MARKETS['spot']}


# %%
async def collateral(symbol: str) -> Collateral:
  info = await client.spot.http.market.exchange_info(symbol=symbol)
  quote = info['symbols'][0]['quoteAsset']
  account = await client.spot.http.account.info()
  balance = next((b for b in account['balances'] if b['asset'] == quote), None)
  free = Decimal(balance['free']) if balance else Decimal(0)
  locked = Decimal(balance['locked']) if balance else Decimal(0)
  return Collateral(equity=free + locked, free_collateral=free)


{symbol: await collateral(symbol) for symbol in MARKETS['spot']}


# %%
async def available_notional(symbol: str) -> Decimal:
  c = await collateral(symbol)
  return c.free_collateral


{symbol: await available_notional(symbol) for symbol in MARKETS['spot']}


# %% [markdown]
# ### Mutating (written, never executed)

# %%
async def place_order(symbol: str, order: Order) -> OrderResponse:
  qty = Decimal(order['qty'])
  side: Literal['BUY', 'SELL'] = 'BUY' if qty > 0 else 'SELL'
  quantity = abs(qty)
  price = Decimal(order['price'])
  body: LimitOrderRequest | MarketOrderByQuantityRequest
  if order['type'] == 'MARKET':
    body = {'symbol': symbol, 'side': side, 'type': 'MARKET', 'quantity': quantity}
  elif order['type'] == 'POST_ONLY':
    body = {
      'symbol': symbol,
      'side': side,
      'type': 'LIMIT_MAKER',
      'quantity': quantity,
      'price': price,
    }
  else:
    body = {
      'symbol': symbol,
      'side': side,
      'type': 'LIMIT',
      'quantity': quantity,
      'price': price,
    }
  raw = await client.spot.http.trade.place_order(body)
  return OrderResponse(id=str(raw['orderId']), details=raw)


# Not executed here -- would place a real order on the account.
await place_order(
  'BTCUSDT', {'qty': Decimal('0.0001'), 'price': Decimal('20000'), 'type': 'LIMIT'}
)


# %%
async def cancel_order(symbol: str, id: str):
  return await client.spot.http.trade.cancel_order(symbol=symbol, order_id=id)


# Not executed here -- would cancel a real order on the account.
await cancel_order('BTCUSDT', '123456')


# %% [markdown]
# ### Coverage assessment: `Market` (spot)
#
# **Fully supported for the abstract interface's read side**, live-tested end-to-end
# above: `depth`/`depth_stream`, `rules`, `position`/`collateral`/`available_notional`.
# `open_orders`/`trades_history` both fail live with the same MEXC error (`700007 No
# permission to access the endpoint`) -- a scope this API key doesn't have, not a code
# issue; `trades_stream` (the account's own private-fills feed) works and simply observes
# no fills in the 5-second window, though see the note above the cell: MEXC's private
# deals push has no symbol field at all, so `trades_stream` can't be scoped to one market
# the way `depth_stream`/`open_orders`/`trades_history` are -- it's inherently
# account-wide, unlike the sibling venues explored in `../../kucoin/poc/market.ipynb` and
# `../../binance/poc/market.ipynb`, both of which filter their user-trade push by symbol.
# `place_order`/`cancel_order` are written but never executed, since they would mutate the
# real account.
#
# `rules()` also differs structurally from Binance/KuCoin: MEXC's `exchange_info` carries
# no `PRICE_FILTER`/`LOT_SIZE`-style filter list for spot symbols (its one filter here is
# `PERCENT_PRICE_BY_SIDE`), so `tick_size`/`step_size` are derived from the flat
# `quoteAssetPrecision`/`baseSizePrecision` fields instead -- `fixed_min_qty`/`min_value`/
# `max_qty` are left `None` since MEXC's spot market data reports none of them.

# %% [markdown]
# ## `PerpMarket` (USDT-M futures)

# %%
async def perp_depth(symbol: str, *, levels: int | None = None) -> Book:
  raw = await client.futures.http.market.depth(symbol=symbol, limit=levels)
  data = raw.get('data')
  assert data is not None, f'no depth data for {symbol}: {raw}'
  return Book(
    bids=[Book.Entry(Decimal(str(p)), Decimal(str(q))) for p, q, _ in data['bids']],
    asks=[Book.Entry(Decimal(str(p)), Decimal(str(q))) for p, q, _ in data['asks']],
  )


{symbol: await perp_depth(symbol, levels=5) for symbol in MARKETS['perp']}


# %%
def perp_depth_stream(symbol: str):
  def to_book(msg: DepthPushMessage) -> Book:
    data = msg['data']
    return Book(
      bids=[Book.Entry(Decimal(str(p)), Decimal(str(q))) for p, q, _ in data['bids']],
      asks=[Book.Entry(Decimal(str(p)), Decimal(str(q))) for p, q, _ in data['asks']],
    )

  return client.futures.streams.market.depth(symbol).map(to_book)


books: list[Book] = []
async with perp_depth_stream('BTC_USDT') as stream:
  async for book in stream:
    books.append(book)
    if len(books) >= 3:
      break
books


# %%
async def perp_rules(symbol: str) -> Rules:
  raw = await client.futures.http.market.contract_info(symbol=symbol)
  spec = raw.get('data')
  assert spec is not None and not isinstance(spec, list), (
    f'no contract spec for {symbol}: {raw}'
  )
  return Rules(
    fee_asset=spec['settleCoin'],
    tick_size=Decimal(str(spec['priceUnit'])),
    step_size=Decimal(str(spec['volUnit'])),
    fixed_min_qty=Decimal(str(spec['minVol'])),
    max_qty=Decimal(str(spec['maxVol'])),
    maker_fee=Decimal(str(spec['makerFeeRate'])),
    taker_fee=Decimal(str(spec['takerFeeRate'])),
    api=spec['apiAllowed'],
    details=spec,
  )


{symbol: await perp_rules(symbol) for symbol in MARKETS['perp']}


# %% [markdown]
# `open_orders`/`trades_history`/`position`/`collateral`/`available_notional` all fail
# live with the same MEXC futures error -- this API key isn't enabled for futures account
# read access, confirmed by the response code, not a code issue:

# %%
async def perp_open_orders(symbol: str) -> list[OrderState]:
  raw = (
    await client.futures.http.trade.open_orders(symbol, page_num=1, page_size=100)
  ).get('data') or []
  out: list[OrderState] = []
  for o in raw:
    vol = Decimal(str(o['vol']))
    sign = (
      1 if o['side'] in (1, 2) else -1
    )  # 1 open long, 2 close short -> net buy direction
    out.append(
      OrderState(
        id=str(o['orderId']),
        price=Decimal(str(o['price'])),
        qty=sign * vol,
        filled_qty=sign * Decimal(str(o['dealVol'])),
        active=o['state'] in (1, 2),
        details=o,
      )
    )
  return out


try:
  perp_open_orders_result = {
    symbol: await perp_open_orders(symbol) for symbol in MARKETS['perp']
  }
except ApiError as e:
  perp_open_orders_result = e
perp_open_orders_result


# %%
async def perp_trades_history(
  symbol: str, start: datetime, end: datetime
) -> list[Trade]:
  raw = (
    await client.futures.http.trade.order_deals(
      symbol=symbol,
      start_time=start,
      end_time=end,
      page_num=1,
      page_size=100,
    )
  ).get('data') or []
  out: list[Trade] = []
  for d in raw:
    vol = Decimal(str(d['vol']))
    sign = 1 if d['side'] in (1, 2) else -1
    out.append(
      Trade(
        id=str(d['id']),
        price=Decimal(str(d['price'])),
        qty=sign * vol,
        time=d['timestamp'],
        maker=not d['taker'],
        fee=Trade.Fee(amount=Decimal(str(d['fee'])), asset=d['feeCurrency'])
        if d['fee']
        else None,
        details=d,
      )
    )
  return out


end = datetime.now(timezone.utc)
start = end - timedelta(hours=24)
try:
  perp_trades_history_result = {
    symbol: await perp_trades_history(symbol, start, end) for symbol in MARKETS['perp']
  }
except ApiError as e:
  perp_trades_history_result = e
perp_trades_history_result


# %% [markdown]
# `perp_trades_stream` (the account's own fill feed, `personal.order.deal`) authenticates
# at the WebSocket layer independently of the REST futures-read scope above, so unlike the
# REST calls it connects live and simply observes no fills in the window:

# %%
def perp_trades_stream(symbol: str):
  def to_trade(msg: OrderDealPushMessage) -> Trade:
    d = msg['data']
    vol = Decimal(str(d['vol']))
    sign = 1 if d['side'] in (1, 2) else -1
    return Trade(
      id=str(d['id']),
      price=Decimal(str(d['price'])),
      qty=sign * vol,
      time=d['timestamp'],
      maker=not d['taker'],
      fee=Trade.Fee(amount=Decimal(str(d['fee'])), asset=d['feeCurrency'])
      if d['fee']
      else None,
      details=d,
    )

  return (
    client.futures.streams.user.my_trades()
    .filter(lambda msg: msg['data']['symbol'] == symbol)
    .map(to_trade)
  )


async with perp_trades_stream('BTC_USDT') as stream:
  it = aiter(stream)
  try:
    trade = await asyncio.wait_for(anext(it), timeout=5.0)
  except asyncio.TimeoutError:
    trade = 'no new trades observed in 5s (expected -- no live trading on this account)'
trade


# %%
async def perp_position(symbol: str) -> PerpPosition:
  raw = (await client.futures.http.position.open(symbol=symbol)).get('data') or []
  if not raw:
    return PerpPosition()
  p = raw[0]
  sign = 1 if p['positionType'] == 1 else -1
  return PerpPosition(
    size=sign * Decimal(str(p['holdVol'])),
    entry_price=Decimal(str(p['holdAvgPrice'])),
  )


try:
  perp_position_result = {
    symbol: await perp_position(symbol) for symbol in MARKETS['perp']
  }
except ApiError as e:
  perp_position_result = e
perp_position_result


# %%
async def perp_collateral(symbol: str) -> PerpCollateral:
  raise NotImplementedError(
    'not supported: MEXC reports no maintenance-margin figure -- neither '
    'futures.http.account.assets nor futures.http.position.open carries one, and '
    'PerpCollateral.maintenance_margin is required'
  )
  contract = await client.futures.http.market.contract_info(symbol=symbol)
  spec = contract.get('data')
  assert spec is not None and not isinstance(spec, list), (
    f'no contract spec for {symbol}: {contract}'
  )
  assets = (await client.futures.http.account.assets()).get('data') or []
  positions = (await client.futures.http.position.open(symbol=symbol)).get('data') or []
  row = next((a for a in assets if a['currency'] == spec['settleCoin']), None)
  equity = Decimal(str(row['equity'])) if row else Decimal(0)
  free_collateral = Decimal(str(row['availableBalance'])) if row else Decimal(0)
  position = positions[0] if positions else None
  if position is not None:
    notional = (
      Decimal(str(position['holdVol']))
      * Decimal(str(position['holdAvgPrice']))
      * Decimal(str(spec['contractSize']))
    )
    initial_margin = Decimal(str(position['im']))
    maintenance_margin = Decimal(0)
    leverage = notional / equity if equity > 0 else Decimal(0)
    margin_mode = 'isolated' if position['openType'] == 1 else 'cross'
  else:
    initial_margin = Decimal(0)
    maintenance_margin = Decimal(0)
    leverage = Decimal(0)
    margin_mode = 'cross'
  return PerpCollateral(
    equity=equity,
    free_collateral=free_collateral,
    initial_margin=initial_margin,
    maintenance_margin=maintenance_margin,
    leverage=leverage,
    margin_mode=margin_mode,
  )


# not executed: not supported -- no venue-reported maintenance margin (see the coverage note)
{symbol: await perp_collateral(symbol) for symbol in MARKETS['perp']}


# %%
async def perp_available_notional(symbol: str) -> Decimal:
  contract = await client.futures.http.market.contract_info(symbol=symbol)
  spec = contract.get('data')
  assert spec is not None and not isinstance(spec, list), (
    f'no contract spec for {symbol}: {contract}'
  )
  assets = (await client.futures.http.account.assets()).get('data') or []
  row = next((a for a in assets if a['currency'] == spec['settleCoin']), None)
  free_collateral = Decimal(str(row['availableBalance'])) if row else Decimal(0)
  return free_collateral * spec['maxLeverage']


try:
  perp_available_notional_result = {
    symbol: await perp_available_notional(symbol) for symbol in MARKETS['perp']
  }
except ApiError as e:
  perp_available_notional_result = e
perp_available_notional_result


# %%
async def index(symbol: str) -> Decimal:
  raw = await client.futures.http.market.index_price(symbol)
  data = raw.get('data')
  assert data is not None, f'no index price for {symbol}: {raw}'
  return Decimal(str(data['indexPrice']))


{symbol: await index(symbol) for symbol in MARKETS['perp']}


# %%
async def next_funding(symbol: str) -> NextFunding:
  raw = await client.futures.http.market.funding_rate(symbol)
  data = raw.get('data')
  assert data is not None, f'no funding rate for {symbol}: {raw}'
  return NextFunding(
    rate=Decimal(str(data['fundingRate'])),
    time=data['nextSettleTime'],
    interval=timedelta(hours=data['collectCycle']),
  )


{symbol: await next_funding(symbol) for symbol in MARKETS['perp']}


# %%
async def funding_rates(
  symbol: str,
  start: datetime | None = None,
  end: datetime | None = None,
) -> list[FundingRate]:
  # funding_rate_history has no start/end params -- only page_num/page_size, newest
  # settlement first -- so the window is applied client-side while paging back in time.
  out: list[FundingRate] = []
  page_num = 1
  while True:
    raw = await client.futures.http.market.funding_rate_history(
      symbol=symbol,
      page_num=page_num,
      page_size=100,
    )
    page = raw.get('data')
    assert page is not None, f'no funding rate history for {symbol}: {raw}'
    for r in page['resultList']:
      time = r['settleTime']
      if start is not None and time < start:
        return out
      if end is None or time <= end:
        out.append(FundingRate(rate=Decimal(str(r['fundingRate'])), time=time))
    if page_num >= page['totalPage']:
      return out
    page_num += 1


end = datetime.now(timezone.utc)
start = end - timedelta(days=7)
{symbol: await funding_rates(symbol, start, end) for symbol in MARKETS['perp']}


# %% [markdown]
# `funding_payments` fails live with the same futures-read-access error as the other
# account-scoped futures endpoints above:

# %%
async def funding_payments(
  symbol: str, start: datetime, end: datetime
) -> list[FundingPayment]:
  # MEXC's `funding` field convention (positive = received vs. paid) isn't verifiable
  # live here (blocked by the same futures-read-access scope) -- assumed by symmetry
  # with typed_binance's `income`, i.e. negated to match FundingPayment's
  # "positive = paid" convention.
  # funding_records has no start/end params either -- only page_num/page_size, newest
  # settlement first, same client-side windowing as funding_rates above.
  out: list[FundingPayment] = []
  page_num = 1
  while True:
    raw = await client.futures.http.account.funding_records(
      symbol=symbol,
      page_num=page_num,
      page_size=100,
    )
    page = raw.get('data')
    assert page is not None, f'no funding records for {symbol}: {raw}'
    for r in page['resultList']:
      time = r['settleTime']
      if time < start:
        return out
      if time <= end:
        out.append(FundingPayment(amount=-Decimal(str(r['funding'])), time=time))
    if page_num >= page['totalPage']:
      return out
    page_num += 1


end = datetime.now(timezone.utc)
start = end - timedelta(days=7)
try:
  funding_payments_result = {
    symbol: await funding_payments(symbol, start, end) for symbol in MARKETS['perp']
  }
except ApiError as e:
  funding_payments_result = e
funding_payments_result


# %% [markdown]
# ### Mutating (written, never executed)
#
# MEXC futures orders need a margin mode (`openType`) and, for isolated margin, a
# `leverage` -- neither is part of the abstract `Order`/`Settings` shape yet, so this
# demonstration hardcodes 1x isolated margin as an illustrative simplification.

# %%
async def perp_place_order(symbol: str, order: Order) -> OrderResponse:
  contract = await client.futures.http.market.contract_info(symbol=symbol)
  spec = contract.get('data')
  assert spec is not None and not isinstance(spec, list), (
    f'no contract spec for {symbol}: {contract}'
  )
  qty = Decimal(order['qty'])
  side: Literal[1, 3] = 1 if qty > 0 else 3  # 1 open long, 3 open short
  vol = float(abs(qty) / Decimal(str(spec['contractSize'])))
  price = float(Decimal(order['price']))
  order_type: Literal[1, 2, 5]  # 1 limit, 2 post-only, 5 market
  if order['type'] == 'MARKET':
    order_type = 5
  elif order['type'] == 'POST_ONLY':
    order_type = 2
  else:
    order_type = 1
  body: IsolatedMarginOrder = {
    'symbol': symbol,
    'price': price,
    'vol': vol,
    'leverage': 1,
    'side': side,
    'type': order_type,
    'openType': 1,
  }
  raw = await client.futures.http.trade.submit_order(body)
  order_id = raw.get('data')
  assert order_id is not None, f'no order id in response: {raw}'
  return OrderResponse(id=str(order_id), details=raw)


# Not executed here -- would place a real order on the account.
await perp_place_order(
  'BTC_USDT', {'qty': Decimal('0.001'), 'price': Decimal('20000'), 'type': 'LIMIT'}
)


# %%
async def perp_cancel_order(order_id: str):
  return await client.futures.http.trade.cancel_order([order_id])


# Not executed here -- would cancel a real order on the account.
await perp_cancel_order('123456')

# %% [markdown]
# ### Coverage assessment: `PerpMarket` (USDT-M futures)
#
# **Present and broader than production.** Unlike `tribulnation.mexc.market`, which has no
# `PerpExchange`/`PerpMarket` implementation at all (the equivalent legacy PoC notebook's
# coverage note flags this as an absent pillar), `typed_mexc` has a complete, independently
# transported `futures` surface (`client.futures.http.{market,account,position,trade}`
# plus `client.futures.streams`)
# covering every method the abstract `PerpMarket` interface needs: `depth`/`depth_stream`,
# `rules`, `open_orders`/`trades_history`/`trades_stream`, `position`/`collateral`/
# `available_notional`, `index`/`next_funding`/`funding_rates`/`funding_payments`,
# `perp_position`/`perp_collateral`, and `place_order`/`cancel_order` (written, never
# executed). This is the single biggest surface gap this rewrite found relative to what
# the 4 legacy notebooks (importing production `tribulnation.mexc` directly) could cover.
#
# Public futures market data (`depth`/`depth_stream`, `rules` via `contract_info`, `index`,
# `next_funding`, `funding_rates`) is **fully live-tested** above. Every account-scoped
# REST call (`open_orders`, `trades_history`, `position`/`collateral`/
# `available_notional`, `funding_payments`) fails live with `701 Please enable API Key
# read access` / `703 Trading information read access is required` -- this API key isn't
# enabled for futures account access at all, not a code issue. `perp_trades_stream`
# (`personal.order.deal`) is the one account-scoped call that *does* work live despite
# that: MEXC's futures user WebSocket authenticates independently of the REST scope, so it
# connects and simply observes no fills in the window, mirroring spot's `trades_stream`
# above. `place_order`/`cancel_order` are written but never executed.
#
# `perp_trades_history` was blocked on typed-mexc's two `OrderDeal` declarations (the
# taker flag under two spellings, `timestamp` as `int | str`). typed-mexc 3.0 settles both
# -- `taker` is required and `timestamp` is an epoch-millis `datetime` -- so the mapping is
# written and runs; it returns the same `703` as the other account-scoped futures reads, so
# its rows stay unverified rather than blocked.
#
# One method is not mapped: `perp_collateral` is **not supported**, because MEXC reports no
# maintenance-margin figure (neither `futures.http.account.assets` nor
# `futures.http.position.open` carries one) and `PerpCollateral.maintenance_margin` is
# required. `position.leverage` exposes the account's current `mmr`, but a figure computed
# from it would be derived, not read.
#
# One unverified assumption remains: `funding_payments`' sign (`positive = paid`) is
# asserted by symmetry with `typed_binance`'s equivalent `income` field, not confirmed
# against a live MEXC response, because the account-scoped call fails with `703`.
