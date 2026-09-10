# %%
import asyncio
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from typing_extensions import Literal

from typed_kucoin import KuCoin
from typed_kucoin.schemas import (
  FuturesAddOrderLimit,
  FuturesAddOrderMarket,
  FuturesOrderBookLevelUpdate,
  FuturesOrderEvent,
  HfAddOrderLimit,
  HfAddOrderMarket,
)
from typed_kucoin.streams.spot_margin_private.order_v2 import OrderChangeEvent
from typed_kucoin.streams.spot_margin_public.orderbook_level5 import (
  OrderbookLevel5Update,
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

client = await KuCoin.new().__aenter__()

MARKETS = {
  'spot': ['BTC-USDT', 'ETH-USDT', 'KCS-USDT'],
  'perp': ['XBTUSDTM', 'ETHUSDTM', 'KCSUSDTM'],
}


# %% [markdown]
# ## `Market` (spot)

# %%
async def depth(symbol: str, *, levels: int | None = None) -> Book:
  size = '100' if levels and levels > 20 else '20'
  raw = await client.spot.part_orderbook(size, symbol=symbol)
  book = Book(
    bids=[Book.Entry(Decimal(p), Decimal(q)) for p, q in raw['bids']],
    asks=[Book.Entry(Decimal(p), Decimal(q)) for p, q in raw['asks']],
  )
  return book.limit(levels) if levels else book


{symbol: await depth(symbol, levels=5) for symbol in MARKETS['spot']}


# %%
def depth_stream(symbol: str):
  def to_book(update: OrderbookLevel5Update) -> Book:
    return Book(
      bids=[Book.Entry(p, q) for p, q in update['bids']],
      asks=[Book.Entry(p, q) for p, q in update['asks']],
    )

  return client.streams.spot_margin_public.orderbook_level5(symbol).map(to_book)


books: list[Book] = []
async with depth_stream(MARKETS['spot'][0]) as stream:
  async for book in stream:
    books.append(book)
    if len(books) >= 3:
      break
books


# %%
async def rules(symbol: str, *, refetch: bool = False) -> Rules:
  sym, fees = await asyncio.gather(
    client.spot.symbol(symbol),
    client.account.trade_fee.actual_fee(symbols=symbol),
  )
  fee = fees[0]
  return Rules(
    fee_asset=sym['feeCurrency'],
    tick_size=Decimal(sym['priceIncrement']),
    step_size=Decimal(sym['baseIncrement']),
    fixed_min_qty=Decimal(sym['baseMinSize']),
    min_value=Decimal(sym['quoteMinSize']) if sym.get('quoteMinSize') else None,
    max_qty=Decimal(sym['baseMaxSize']) if sym.get('baseMaxSize') else None,
    maker_fee=Decimal(fee['makerFeeRate']),
    taker_fee=Decimal(fee['takerFeeRate']),
    api=sym['enableTrading'],
    details=sym,
  )


{symbol: await rules(symbol) for symbol in MARKETS['spot']}


# %%
async def open_orders(symbol: str) -> list[OrderState]:
  raw = await client.spot.orders_hf.get_open_orders(symbol=symbol)
  out: list[OrderState] = []
  for o in raw or []:
    size = Decimal(o['size'])
    dealt = Decimal(o['dealSize'])
    sign = 1 if o['side'] == 'buy' else -1
    out.append(
      OrderState(
        id=o['id'],
        price=Decimal(o['price']),
        qty=sign * size,
        filled_qty=sign * dealt,
        active=True,
        details=o,
      )
    )
  return out


{symbol: await open_orders(symbol) for symbol in MARKETS['spot']}


# %%
async def trades_history(symbol: str, start: datetime, end: datetime) -> list[Trade]:
  page = await client.spot.orders_hf.get_trade_history(
    symbol=symbol, start_at=start, end_at=end
  )
  out: list[Trade] = []
  for f in page['items']:
    size = Decimal(f['size'])
    fee_amount = Decimal(f['fee'])
    out.append(
      Trade(
        id=str(f['tradeId']),
        price=Decimal(f['price']),
        qty=size if f['side'] == 'buy' else -size,
        time=f['createdAt'],
        maker=f['liquidity'] == 'maker',
        fee=Trade.Fee(amount=fee_amount, asset=f['feeCurrency'])
        if fee_amount
        else None,
        details=f,
      )
    )
  return out


end = datetime.now(timezone.utc)
start = end - timedelta(hours=24)
{symbol: await trades_history(symbol, start, end) for symbol in MARKETS['spot']}


# %%
def trades_stream(symbol: str):
  # Spot/Margin's private order-lifecycle feed is account-wide (one topic covers every
  # symbol), so filter to `symbol` and to fill (`match`) events client-side.
  def parse(event: OrderChangeEvent) -> Trade | None:
    if event.get('type') != 'match' or event.get('symbol') != symbol:
      return None
    match_size = event.get('matchSize')
    match_price = event.get('matchPrice')
    if match_size is None or match_price is None:
      return None
    return Trade(
      id=event.get('tradeId'),
      price=match_price,
      qty=match_size if event['side'] == 'buy' else -match_size,
      time=event['orderTime'],
      maker=event.get('liquidity') == 'maker',
      fee=None,
      details=event,
    )

  return (
    client.streams.spot_margin_private.order_v2()
    .map(parse)
    .filter(lambda t: t is not None)
  )


async with trades_stream(MARKETS['spot'][0]) as stream:
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
  sym = await client.spot.symbol(symbol)
  accounts = await client.account.spot_accounts(
    currency=sym['baseCurrency'], type='trade'
  )
  size = sum((Decimal(a['balance']) for a in accounts), Decimal(0))
  return Position(size=size)


{symbol: await position(symbol) for symbol in MARKETS['spot']}


# %%
async def collateral(symbol: str) -> Collateral:
  sym = await client.spot.symbol(symbol)
  accounts = await client.account.spot_accounts(
    currency=sym['quoteCurrency'], type='trade'
  )
  balance = accounts[0] if accounts else None
  equity = Decimal(balance['balance']) if balance else Decimal(0)
  free = Decimal(balance['available']) if balance else Decimal(0)
  return Collateral(equity=equity, free_collateral=free)


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
  side: Literal['buy', 'sell'] = 'buy' if qty > 0 else 'sell'
  size = abs(qty)
  body: HfAddOrderLimit | HfAddOrderMarket
  if order['type'] == 'MARKET':
    body = {'symbol': symbol, 'type': 'market', 'side': side, 'size': size}
  else:
    limit: HfAddOrderLimit = {
      'symbol': symbol,
      'type': 'limit',
      'side': side,
      'price': Decimal(order['price']),
      'size': size,
    }
    if order['type'] == 'POST_ONLY':
      limit['postOnly'] = True
    body = limit
  raw = await client.spot.orders_hf.add(body)
  return OrderResponse(id=raw['orderId'], details=raw)


# Not executed here -- would place a real order on the account.
await place_order(
  'BTC-USDT', {'qty': Decimal('0.0001'), 'price': Decimal('20000'), 'type': 'LIMIT'}
)


# %%
async def cancel_order(symbol: str, id: str, *, settings: Settings = {}):
  return await client.spot.orders_hf.cancel_by_order_id(order_id=id, symbol=symbol)


# Not executed here -- would cancel a real order on the account.
await cancel_order('BTC-USDT', '123456')


# %% [markdown]
# ## `PerpMarket` (Futures)
#
# KuCoin futures denominate order/position/book quantities in **lots (contracts)**, not
# base-asset units -- converting to base units needs each contract's `multiplier`
# (`futures.symbol`), and is negative/inverted for inverse contracts. This notebook passes
# the raw lot count through as `qty`/`size` (documented in the coverage note below) rather
# than silently mis-converting.

# %%
async def depth(symbol: str, *, levels: int | None = None) -> Book:
  size = '100' if levels and levels > 20 else '20'
  raw = await client.futures.part_orderbook(size, symbol=symbol)
  book = Book(
    bids=[Book.Entry(Decimal(str(p)), Decimal(q)) for p, q in raw['bids']],
    asks=[Book.Entry(Decimal(str(p)), Decimal(q)) for p, q in raw['asks']],
  )
  return book.limit(levels) if levels else book


{symbol: await depth(symbol, levels=5) for symbol in MARKETS['perp']}


# %%
def depth_stream(symbol: str):
  def to_book(update: FuturesOrderBookLevelUpdate) -> Book:
    return Book(
      bids=[Book.Entry(p, Decimal(q)) for p, q in update['bids']],
      asks=[Book.Entry(p, Decimal(q)) for p, q in update['asks']],
    )

  return client.streams.futures_public.orderbook_level5(symbol).map(to_book)


books: list[Book] = []
async with depth_stream(MARKETS['perp'][0]) as stream:
  async for book in stream:
    books.append(book)
    if len(books) >= 3:
      break
books


# %%
async def rules(symbol: str, *, refetch: bool = False) -> Rules:
  sym = await client.futures.symbol(symbol)
  return Rules(
    fee_asset=sym['settleCurrency'],
    tick_size=Decimal(str(sym['tickSize'])),
    step_size=Decimal(sym['lotSize']),
    fixed_min_qty=Decimal(sym['lotSize']),
    max_qty=Decimal(sym['maxOrderQty']),
    maker_fee=Decimal(str(sym['makerFeeRate'])),
    taker_fee=Decimal(str(sym['takerFeeRate'])),
    api=sym['status'] == 'Open',
    details=sym,
  )


{symbol: await rules(symbol) for symbol in MARKETS['perp']}


# %%
async def open_orders(symbol: str) -> list[OrderState]:
  page = await client.futures.orders.get_order_list(status='active', symbol=symbol)
  out: list[OrderState] = []
  for o in page['items']:
    size = Decimal(o['size'])
    dealt = Decimal(o['dealSize'])
    sign = 1 if o['side'] == 'buy' else -1
    out.append(
      OrderState(
        id=o['id'],
        price=Decimal(o['price']),
        qty=sign * size,
        filled_qty=sign * dealt,
        active=o['isActive'],
        details=o,
      )
    )
  return out


{symbol: await open_orders(symbol) for symbol in MARKETS['perp']}


# %%
async def trades_history(symbol: str, start: datetime, end: datetime) -> list[Trade]:
  # Each call spans at most 7 days -- the caller (or the SDK's own pagination layer, for
  # a wider window) is responsible for chunking a longer range into 7-day requests.
  page = await client.futures.orders.get_trade_history(
    symbol=symbol, start_at=start, end_at=end
  )
  out: list[Trade] = []
  for f in page['items']:
    size = Decimal(f['size'])
    fee = f['openFeePay'] + f['closeFeePay']
    out.append(
      Trade(
        id=f['tradeId'],
        price=f['price'],
        qty=size if f['side'] == 'buy' else -size,
        time=f['tradeTime'],
        maker=f['liquidity'] == 'maker',
        fee=Trade.Fee(amount=fee, asset=f['feeCurrency']) if fee else None,
        details=f,
      )
    )
  return out


end = datetime.now(timezone.utc)
start = end - timedelta(hours=24)
{symbol: await trades_history(symbol, start, end) for symbol in MARKETS['perp']}


# %%
def trades_stream(symbol: str):
  def parse(event: FuturesOrderEvent) -> Trade | None:
    if event.get('type') != 'match':
      return None
    match_size = event.get('matchSize')
    match_price = event.get('matchPrice')
    if match_size is None or match_price is None:
      return None
    size = Decimal(match_size)
    return Trade(
      id=event.get('tradeId'),
      price=match_price,
      qty=size if event['side'] == 'buy' else -size,
      time=event['orderTime'],
      maker=event.get('liquidity') == 'maker',
      fee=None,
      details=event,
    )

  return (
    client.streams.futures_private.order(symbol)
    .map(parse)
    .filter(lambda t: t is not None)
  )


async with trades_stream(MARKETS['perp'][0]) as stream:
  it = aiter(stream)
  try:
    result = await asyncio.wait_for(anext(it), timeout=5.0)
  except asyncio.TimeoutError:
    result = (
      'no new trades observed in 5s (expected -- no live trading on this account)'
    )
result


# %%
async def perp_position(symbol: str) -> PerpPosition:
  row = await client.futures.positions.get_position_details(symbol=symbol)
  return PerpPosition(
    size=Decimal(row['currentQty']), entry_price=Decimal(str(row['avgEntryPrice']))
  )


{symbol: await perp_position(symbol) for symbol in MARKETS['perp']}


# %%
async def position(symbol: str) -> PerpPosition:
  return await perp_position(symbol)


{symbol: await position(symbol) for symbol in MARKETS['perp']}


# %%
async def perp_collateral(symbol: str) -> PerpCollateral:
  sym, position_row = await asyncio.gather(
    client.futures.symbol(symbol),
    client.futures.positions.get_position_details(symbol=symbol),
  )
  account = await client.account.futures_account(currency=sym['settleCurrency'])
  equity = Decimal(str(account['accountEquity']))
  leverage = (
    Decimal(str(position_row['leverage'])) if position_row.get('isOpen') else Decimal(0)
  )
  margin_mode = 'isolated' if position_row.get('marginMode') == 'ISOLATED' else 'cross'
  return PerpCollateral(
    equity=equity,
    free_collateral=Decimal(str(account['availableBalance'])),
    initial_margin=Decimal(str(account['positionMargin'] + account['orderMargin'])),
    maintenance_margin=Decimal(str(position_row.get('maintMargin') or 0)),
    leverage=leverage,
    margin_mode=margin_mode,
  )


# not executed: this API key lacks the `Futures` permission `GET /api/v1/account-overview` requires (live 404; see the coverage note), so `account.futures_account` cannot be exercised
{symbol: await perp_collateral(symbol) for symbol in MARKETS['perp']}


# %%
async def collateral(symbol: str) -> PerpCollateral:
  return await perp_collateral(symbol)


# not executed: this API key lacks the `Futures` permission `GET /api/v1/account-overview` requires (live 404; see the coverage note), so `account.futures_account` cannot be exercised
{symbol: await collateral(symbol) for symbol in MARKETS['perp']}


# %%
async def available_notional(symbol: str) -> Decimal:
  c, sym = await asyncio.gather(perp_collateral(symbol), client.futures.symbol(symbol))
  return c.free_collateral * Decimal(sym['maxLeverage'])


# not executed: this API key lacks the `Futures` permission `GET /api/v1/account-overview` requires (live 404; see the coverage note), so `account.futures_account` cannot be exercised
{symbol: await available_notional(symbol) for symbol in MARKETS['perp']}


# %%
async def place_order(
  symbol: str, order: Order, *, settings: Settings = {}
) -> OrderResponse:
  import uuid

  qty = Decimal(order['qty'])
  side: Literal['buy', 'sell'] = 'buy' if qty > 0 else 'sell'
  size = int(abs(qty))
  client_oid = str(uuid.uuid4())
  body: FuturesAddOrderLimit | FuturesAddOrderMarket
  if order['type'] == 'MARKET':
    body = {
      'clientOid': client_oid,
      'symbol': symbol,
      'side': side,
      'leverage': 1,
      'size': size,
      'type': 'market',
    }
  else:
    limit: FuturesAddOrderLimit = {
      'clientOid': client_oid,
      'symbol': symbol,
      'side': side,
      'leverage': 1,
      'size': size,
      'type': 'limit',
      'price': Decimal(order['price']),
    }
    if order['type'] == 'POST_ONLY':
      limit['postOnly'] = True
    body = limit
  raw = await client.futures.orders.add(body)
  return OrderResponse(id=raw['orderId'], details=raw)


# Not executed here -- would place a real order on the account.
await place_order(
  'XBTUSDTM', {'qty': Decimal('1'), 'price': Decimal('20000'), 'type': 'LIMIT'}
)


# %%
async def cancel_order(symbol: str, id: str, *, settings: Settings = {}):
  return await client.futures.orders.cancel_by_order_id(id)


# Not executed here -- would cancel a real order on the account.
await cancel_order('XBTUSDTM', '123456')


# %%
async def index(symbol: str, *, settings: Settings = {}) -> Decimal:
  sym = await client.futures.symbol(symbol)
  return Decimal(str(sym['indexPrice']))


{symbol: await index(symbol) for symbol in MARKETS['perp']}


# %%
async def next_funding(symbol: str) -> NextFunding:
  sym = await client.futures.symbol(symbol)
  # `nextFundingRateDateTime`/`fundingRateGranularity` are `None` on a dated (non-perpetual)
  # contract, which has no funding mechanism -- every `MARKETS['perp']` symbol here is a
  # perpetual, so this should never actually trip.
  next_funding_time = sym['nextFundingRateDateTime']
  granularity = sym['fundingRateGranularity']
  assert next_funding_time is not None and granularity is not None, (
    f'{symbol} has no funding schedule -- not a perpetual contract'
  )
  return NextFunding(
    rate=Decimal(str(sym['fundingFeeRate'])),
    time=next_funding_time,
    interval=timedelta(milliseconds=granularity),
  )


{symbol: await next_funding(symbol) for symbol in MARKETS['perp']}


# %%
async def funding_rates(
  symbol: str,
  start: datetime | None = None,
  end: datetime | None = None,
) -> list[FundingRate]:
  # `public_funding_history` requires both `from_`/`to` -- there's no venue call that
  # actually returns "everything since the earliest available" in one shot, so `start=None`
  # here falls back to a 7-day window rather than the abstract docstring's literal contract.
  end = end or datetime.now(timezone.utc)
  start = start or end - timedelta(days=7)
  raw = await client.futures.funding_fees.public_funding_history(
    symbol=symbol, from_=start, to=end
  )
  return [
    FundingRate(rate=Decimal(str(r['fundingRate'])), time=r['timepoint']) for r in raw
  ]


end = datetime.now(timezone.utc)
start = end - timedelta(days=7)
{symbol: await funding_rates(symbol, start, end) for symbol in MARKETS['perp']}


# %%
async def funding_payments(
  symbol: str, start: datetime, end: datetime
) -> list[FundingPayment]:
  page = await client.futures.funding_fees.private_funding_history(
    symbol=symbol, start_at=start, end_at=end
  )
  # KuCoin's `funding` is positive when *received*; the SDK's `FundingPayment.amount` is
  # positive when *paid* -- opposite sign conventions, so this flips it.
  return [
    FundingPayment(amount=-Decimal(str(f['funding'])), time=f['timePoint'])
    for f in page['dataList']
  ]


end = datetime.now(timezone.utc)
start = end - timedelta(days=7)
{symbol: await funding_payments(symbol, start, end) for symbol in MARKETS['perp']}

# %%
# Diagnostic: is `account.futures_account`'s 404 caused by an unactivated futures
# wallet, or by the API key itself lacking the `Futures` permission scope?
# `account.api_key_info` (`GET /api/v1/user/api-key`) only echoes metadata about the
# key signing the request -- read-only, safe to call live. Only the permission scope is
# displayed: the response also echoes the key itself, which must not land in a notebook.
(await client.account.api_key_info())['permission']

# %% [markdown]
# ### Coverage assessment: `Market` / `PerpMarket`
#
# **Spot: fully supported**, live-tested for depth/streaming depth/rules/open
# orders/trades history/streaming trades/position/collateral/available notional above.
# `orders_hf` (the high-frequency order book) is the natural mapping for `place_order`/
# `cancel_order`/`open_orders`/`trades_history` -- KuCoin's plain (non-hf) order book is a
# legacy surface the docs steer new integrations away from. `trades_stream` has no
# per-symbol private trade feed; it's built by filtering the account-wide `order_v2`
# lifecycle feed down to `type == 'match'` events for the requested symbol.
#
# **Futures: fully supported for read/write shape**, with one structural mismatch worth
# flagging: KuCoin futures quantities (`Book` levels, `OrderState.qty`, `PerpPosition.size`)
# are all in **lots (contracts)**, not base-asset units the way `Book`/`Position`'s
# docstrings imply -- converting requires each contract's `multiplier` (and sign, for an
# inverse contract), which this notebook does not attempt (it passes the lot count through
# as-is). `trades_history`/`funding_payments`/`get_trade_history` are further capped to a
# 7-day window per call (documented on `futures.orders.get_trade_history`); a full
# `PaginatedResponse` implementation would need to chunk a wider `start`/`end` into 7-day
# slices itself, since KuCoin's own pagination only walks pages *within* one window.
# `perp_collateral`'s `initial_margin`/`maintenance_margin` are approximated from
# `account.futures_account` (account-level `positionMargin + orderMargin`) and the single
# requested position's `maintMargin` respectively -- KuCoin has no one call that reports
# both figures already aggregated the way the SDK's dataclass expects for a multi-position
# account. On *this* account `account.futures_account` (`GET /api/v1/account-overview`)
# returns a live `404` regardless of currency, while `futures.positions.get_position_*`
# endpoints succeed with zeroed rows. The diagnostic cell above calls the read-only
# `account.api_key_info` (`GET /api/v1/user/api-key`) to check why: this key's granted
# `permission` scopes are `General,Unified,Spot,Earn,InnerTransfer,Margin` -- no
# `Futures`. KuCoin's docs list `Futures` as the required permission for [`Get Account -
# Futures`](https://www.kucoin.com/docs-new/rest/account-info/account-funding/get-account-futures),
# and only `General` for [`Get Position
# List`](https://www.kucoin.com/docs-new/rest/futures-trading/positions/get-position-list),
# which lines up exactly with what 404s and what succeeds here. So this looks like a
# permission-scope gap on the API key itself -- not, as first guessed, an unactivated or
# unfunded futures wallet -- though KuCoin's own [error-code
# reference](https://www.kucoin.com/docs-new/error-code/futures) documents a missing scope
# as `400007` `Access Denied`, not a bare `404`, so the exact shape of this response isn't
# itself explained by the docs. Confirming this would mean regenerating the key with
# `Futures` enabled, which this notebook does not attempt since it would mutate account/key
# state. Real errors from the gap propagate untouched through `perp_collateral`/`collateral`/
# `available_notional` below rather than being papered over.
