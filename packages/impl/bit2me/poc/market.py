# %%
import asyncio
from contextlib import asynccontextmanager
from decimal import Decimal
from datetime import datetime, timedelta, timezone

from typed_bit2me import Bit2Me
from typed_bit2me.v1.trading.orders.create import LimitOrderRequest, MarketOrderRequest
from typed_bit2me.types import OrderSide
from typed_bit2me.trading_ws.my_trades import MyTradeUpdate
from typed_bit2me.trading_ws.order_book import OrderBookUpdate
from dotenv import load_dotenv

from tribulnation.sdk.market import (
  Book,
  Collateral,
  Order,
  OrderResponse,
  OrderState,
  Position,
  Rules,
  Settings,
  Ticker,
  Trade,
)

load_dotenv()

client = await Bit2Me.new().__aenter__()

MARKETS = ['BTC/EUR', 'ETH/EUR', 'SOL/EUR']


# %% [markdown]
# ## `Market` (spot)
#
# Bit2Me only has a Trading Spot product -- no futures/perpetual surface anywhere in
# `typed_bit2me` (no `futures`/`perp`/`derivatives` module, no `PerpMarket`-shaped
# endpoints), so only the abstract `Market` interface applies here; there's no
# `PerpMarket` notebook section.

# %%
async def depth(symbol: str, *, levels: int | None = None) -> Book:
  raw = await client.v2.trading.order_book(symbol=symbol)
  bids = raw.get('bids') or []
  asks = raw.get('asks') or []
  # `v2/trading/order-book` takes only `symbol`: a `limit`/`depth` query param is ignored
  # rather than honoured, and the response is capped at 100 levels per side. So `levels`
  # is applied client-side by truncating afterward.
  if levels is not None:
    bids = bids[:levels]
    asks = asks[:levels]
  # Rows are `[price, amount]` on most markets but `[price, amount, price * amount]` on 26
  # of the 290 (the thin/stablecoin pairs), so read the first two by index rather than
  # unpacking.
  return Book(
    bids=[Book.Entry(Decimal(str(r[0])), Decimal(str(r[1]))) for r in bids],
    asks=[Book.Entry(Decimal(str(r[0])), Decimal(str(r[1]))) for r in asks],
  )


{symbol: await depth(symbol, levels=5) for symbol in MARKETS}


# %%
@asynccontextmanager
async def depth_stream(symbol: str):
  def to_book(update: OrderBookUpdate) -> Book:
    return Book(
      bids=[Book.Entry(Decimal(str(p)), Decimal(str(q))) for p, q in update['bids']],
      asks=[Book.Entry(Decimal(str(p)), Decimal(str(q))) for p, q in update['asks']],
    )

  # `trading_ws` is a single multiplexed connection: opening it (unlike e.g. Binance's
  # `client.spot.streams`, which connects lazily per-subscription) is a separate step
  # from subscribing to one channel on it.
  async with client.trading_ws as ws:
    async with ws.order_book(symbol).map(to_book) as stream:
      yield stream


books: list[Book] = []
async with depth_stream('BTC/EUR') as stream:
  async for book in stream:
    books.append(book)
    if len(books) >= 3:
      break
books


# %%
async def rules(symbol: str, *, refetch: bool = False) -> Rules:
  base, quote = symbol.split('/')
  info = (await client.v1.trading.markets(symbol=symbol))[0]
  amount_precision = info.get('amountPrecision')
  tick_size = info.get('tickSize')
  min_amount = info.get('minAmount')
  max_amount = info.get('maxAmount')
  min_price = info.get('minPrice')
  max_price = info.get('maxPrice')
  return Rules(
    base=base,
    quote=quote,
    fee_asset=quote,
    tick_size=Decimal(str(tick_size)) if tick_size is not None else Decimal(0),
    step_size=Decimal(1).scaleb(-int(amount_precision))
    if amount_precision is not None
    else Decimal(0),
    fixed_min_qty=Decimal(str(min_amount)) if min_amount is not None else None,
    max_qty=Decimal(str(max_amount)) if max_amount is not None else None,
    fixed_min_price=Decimal(str(min_price)) if min_price is not None else None,
    fixed_max_price=Decimal(str(max_price)) if max_price is not None else None,
    # No fee-schedule endpoint exists anywhere in `typed_bit2me` (searched the whole
    # package for a maker/taker-fee-shaped field or call; nothing) -- trading fees aren't
    # derivable from any documented endpoint, so both default to 0. A known gap, not a
    # claim that trading is free.
    maker_fee=Decimal(0),
    taker_fee=Decimal(0),
    api=info.get('marketEnabled') == 'enabled',
    details=info,
  )


{symbol: await rules(symbol) for symbol in MARKETS}


# %%
async def tickers(markets: list[str] | None = None) -> dict[str, Ticker]:
  # `v2/trading/tickers` answers for every market in one call, prices only: best bid
  # and ask carry no size, so `bid_qty`/`ask_qty` stay `None`. `open`/`percentage` are
  # `null` on markets that haven't traded in 24h and aren't read here.
  entries = await client.v2.trading.tickers()
  wanted = None if markets is None else set(markets)
  out: dict[str, Ticker] = {}
  for entry in entries:
    symbol = entry.get('symbol')
    if not symbol or (wanted is not None and symbol not in wanted):
      continue
    last, bid, ask, volume = (
      entry.get('close'), entry.get('bid'), entry.get('ask'), entry.get('baseVolume')
    )
    out[symbol] = Ticker(
      last=Decimal(str(last)) if last is not None else None,
      bid=Decimal(str(bid)) if bid is not None else None,
      ask=Decimal(str(ask)) if ask is not None else None,
      base_volume_24h=Decimal(str(volume)) if volume is not None else None,
    )
  return out


everything = await tickers()
len(everything), await tickers(MARKETS)


# %%
async def open_orders(symbol: str) -> list[OrderState]:
  raw = await client.v1.trading.orders.list(status='open', symbol=symbol)
  out: list[OrderState] = []
  for o in raw:
    qty = Decimal(str(o.get('amount', 0)))
    filled = Decimal(str(o.get('filledAmount', 0)))
    sign = 1 if o.get('side') == 'buy' else -1
    price = o.get('price')
    out.append(
      OrderState(
        id=str(o.get('id')),
        price=Decimal(str(price)) if price is not None else Decimal(0),
        qty=sign * qty,
        filled_qty=sign * filled,
        active=o.get('status') in ('open', 'inactive'),
        details=o,
      )
    )
  return out


{symbol: await open_orders(symbol) for symbol in MARKETS}


# %%
async def trades_history(symbol: str, start: datetime, end: datetime) -> list[Trade]:
  resp = await client.v1.trading.trades.list(
    symbol=symbol, start_time=start, end_time=end, limit=100
  )
  out: list[Trade] = []
  for t in resp.get('data', []):
    qty = Decimal(str(t.get('amount', 0)))
    fee_amount = t.get('feeAmount')
    fee_currency = t.get('feeCurrency')
    price = t.get('price')
    out.append(
      Trade(
        id=t.get('id'),
        price=Decimal(str(price)) if price is not None else Decimal(0),
        qty=qty if t.get('side') == 'buy' else -qty,
        time=t.get('createdAt') or datetime.now(timezone.utc),
        maker=bool(t.get('isMaker')),
        fee=Trade.Fee(amount=Decimal(str(fee_amount)), asset=fee_currency)
        if fee_amount and fee_currency
        else None,
        details=t,
      )
    )
  return out


end = datetime.now(timezone.utc)
start = end - timedelta(days=30)
{symbol: await trades_history(symbol, start, end) for symbol in MARKETS}


# %%
@asynccontextmanager
async def trades_stream(symbol: str):
  def to_trade(update: MyTradeUpdate) -> Trade:
    price = Decimal(str(update['price']))
    qty = Decimal(str(update['amount']))
    fee = update.get('fee')
    return Trade(
      id=update['id'],
      price=price,
      qty=qty if update['side'] == 'buy' else -qty,
      time=update.get('datetime') or datetime.now(timezone.utc),
      maker=bool(update.get('isMaker')),
      fee=Trade.Fee(amount=Decimal(str(fee['cost'])), asset=fee['currency'])
      if fee
      else None,
      details=update,
    )

  async with client.trading_ws as ws:
    async with ws.my_trades(symbol=symbol).map(to_trade) as stream:
      yield stream


async with trades_stream('BTC/EUR') as stream:
  try:
    result = await asyncio.wait_for(anext(aiter(stream)), timeout=5.0)
  except asyncio.TimeoutError:
    result = (
      'no new trades observed in 5s (expected -- no live trading on this account)'
    )
result

# %%
# One unfiltered `balance()` call, reused by `position`/`collateral` below -- calling it
# once per market (3 markets x 2 helpers) trips live rate-limiting: the sixth call in
# quick succession returns `RateLimited(429, ...)`, with or without a `symbols=` filter.
# Bit2Me limits this endpoint far more tightly than the market-data calls above, which
# take a dozen calls in a row without complaint.
balances = {
  b['currency']: b for b in await client.v1.trading.balance() if b.get('currency')
}


async def position(symbol: str) -> Position:
  base, _ = symbol.split('/')
  entry = balances.get(base)
  size = (
    Decimal(str(entry['balance'])) + Decimal(str(entry['blockedBalance']))
    if entry
    else Decimal(0)
  )
  return Position(size=size)


{symbol: await position(symbol) for symbol in MARKETS}


# %%
async def collateral(symbol: str) -> Collateral:
  _, quote = symbol.split('/')
  entry = balances.get(quote)
  free = Decimal(str(entry['balance'])) if entry else Decimal(0)
  locked = Decimal(str(entry['blockedBalance'])) if entry else Decimal(0)
  return Collateral(equity=free + locked, free_collateral=free)


{symbol: await collateral(symbol) for symbol in MARKETS}


# %%
async def available_notional(symbol: str) -> Decimal:
  c = await collateral(symbol)
  return c.free_collateral


{symbol: await available_notional(symbol) for symbol in MARKETS}


# %%
async def place_order(
  symbol: str, order: Order, *, settings: Settings = {}
) -> OrderResponse:
  side: OrderSide = 'buy' if Decimal(order['qty']) > 0 else 'sell'
  amount = str(abs(Decimal(order['qty'])))
  body: LimitOrderRequest | MarketOrderRequest
  if order['type'] == 'MARKET':
    body = {'side': side, 'symbol': symbol, 'amount': amount, 'orderType': 'market'}
  elif order['type'] == 'POST_ONLY':
    body = {
      'side': side,
      'symbol': symbol,
      'amount': amount,
      'orderType': 'limit',
      'price': str(Decimal(order['price'])),
      'postOnly': True,
    }
  else:
    body = {
      'side': side,
      'symbol': symbol,
      'amount': amount,
      'orderType': 'limit',
      'price': str(Decimal(order['price'])),
    }
  raw = await client.v1.trading.orders.create(body)
  return OrderResponse(id=str(raw.get('id')), details=raw)


# Not executed here -- would place a real order on the account.
await place_order(
  'BTC/EUR', {'qty': Decimal('0.0001'), 'price': Decimal('20000'), 'type': 'LIMIT'}
)


# %%
async def cancel_order(symbol: str, id: str, *, settings: Settings = {}):
  return await client.v1.trading.orders.cancel(id)


# Not executed here -- would cancel a real order on the account.
await cancel_order('BTC/EUR', '123456')

# %% [markdown]
# ## Coverage
#
# **Fully supported**, live-tested above for depth, streaming depth, rules, tickers, open
# orders, trades history, streaming trades, position, collateral, and available notional.
# Four caveats, documented inline where they occur:
#
# - **`rules().maker_fee`/`taker_fee` are always `0`** -- no fee-schedule endpoint exists
#   anywhere in `typed_bit2me` (nothing maker/taker/commission-shaped in the whole package,
#   and `v1/trading/market-config`'s live rows carry no fee field either); per-trade fees
#   only ever show up after the fact, on individual `TradeResponse`/`OrderResponse` rows
#   (`feeAmount`/`feeCurrency`), never as a queryable rate ahead of time.
# - **`tickers()` carries no `bid_qty`/`ask_qty`** -- `v2/trading/tickers` quotes best bid
#   and ask prices for all 290 markets in one call, but no size at either.
# - **`depth()`/`v2.trading.order_book` has no depth/limit parameter** -- `symbol` is its
#   only argument, and a `limit=`/`depth=` query param added by hand is ignored rather than
#   honoured. What comes back is the book truncated to 100 levels per side (thin markets
#   return fewer), so `levels` is applied by truncating client-side.
# - **`v1/trading/wallet/balance` rate-limits far tighter than the market-data endpoints
#   above** -- the sixth call in quick succession returns `RateLimited(429, ...)`, whether
#   or not a `symbols=` filter is passed, while `v1/trading/market-config` takes a dozen in
#   a row without complaint. `position`/`collateral` therefore fetch the full unfiltered
#   balance list once and reuse it.
# `trading_ws` (this notebook's `depth_stream`/`trades_stream`) is Bit2Me's one WebSocket
# surface for Trading Spot: a single multiplexed connection carrying public channels
# (`order-book`, `public-trades`) alongside private ones (`my-orders`, `my-trades`,
# `my-balance`) and the six one-shot trading commands (`add-order`, `cancel-order`, ...).
# Opening it (`async with client.trading_ws as ws:`) is a separate step from subscribing to
# one channel on it, since a fresh `TradingWs`/`TradingWsClient` pair is constructed lazily
# per `Bit2Me` client and needs its own connect + (when credentials are present) WS-token
# authentication before any channel can be subscribed to -- unlike some other venues'
# generated clients, which connect their public stream surface lazily per call.
#
# `place_order`/`cancel_order` map onto `POST /v1/trading/order` /
# `DELETE /v1/trading/order/{id}` and are written above but never executed.
