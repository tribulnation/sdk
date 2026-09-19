# %%
# not executed: Legacy account mapping is outside the current public Futures qualification.
import asyncio
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from typing_extensions import Literal

from typed_kraken import Kraken
from typed_kraken.spot.trading.add_order import AddOrderMarket, AddOrderLimit
from typed_kraken.streams.market_data.book import BookMessage
from dotenv import load_dotenv

from tribulnation.sdk.market import (
  Book,
  Fees,
  Collateral,
  Order,
  OrderResponse,
  OrderState,
  Position,
  Rules,
  Settings,
  Trade,
)

load_dotenv()

client = await Kraken.new().__aenter__()

# REST pair identifiers (Kraken "altname", e.g. `pair=` on market_data/trading endpoints).
# `XBTUSDC` is the only pair this account has ever traded, so it is what keeps the
# account-scoped cells (trades_history/position/collateral) from returning empties.
MARKETS = {
  'spot': ['XBTUSD', 'ETHUSD', 'SOLUSD', 'XBTUSDC'],
}

# Kraken WebSocket v2 uses yet another symbol format for the same pairs (`BTC/USD`, not
# the REST altname `XBTUSD` nor the legacy-WS `wsname` `XBT/USD` reported by AssetPairs --
# three different spellings of the same pairs across one client. See coverage notes.
WS_SYMBOLS = {
  'XBTUSD': 'BTC/USD',
  'ETHUSD': 'ETH/USD',
  'SOLUSD': 'SOL/USD',
  'XBTUSDC': 'BTC/USDC',
}


# %% [markdown]
# ## `Market` (spot)
#
# This legacy account PoC is not current public qualification. See `market/public.py`
# for credential-free Spot probes and `dev-docs/kraken-public-market.md` for SDK #33.
# Public Futures mappings below use typed-kraken 0.4.0 through the SDK.


# %%
# not executed: Legacy account mapping is outside the current public Futures qualification.
async def depth(symbol: str, *, levels: int | None = None) -> Book:
  raw = await client.spot.market_data.depth(pair=symbol, count=levels)
  book = next(iter(raw.values()))
  return Book(
    bids=[Book.Entry(Decimal(p), Decimal(q)) for p, q, _ts in book.get('bids', [])],
    asks=[Book.Entry(Decimal(p), Decimal(q)) for p, q, _ts in book.get('asks', [])],
  )


{symbol: await depth(symbol, levels=5) for symbol in MARKETS['spot']}


# %%
# not executed: Legacy account mapping is outside the current public Futures qualification.
def depth_stream(symbol: str, *, levels: Literal[10, 25, 100, 500, 1000] = 10):
  def to_book(msg: BookMessage) -> Book:
    data = msg['data'][0]
    return Book(
      bids=[
        Book.Entry(Decimal(str(e['price'])), Decimal(str(e['qty'])))
        for e in data['bids']
      ],
      asks=[
        Book.Entry(Decimal(str(e['price'])), Decimal(str(e['qty'])))
        for e in data['asks']
      ],
    )

  # `levels` must be one of Kraken's fixed depths (10/25/100/500/1000), unlike the SDK's
  # arbitrary `int | None`.
  return client.streams.market_data.book(symbol=[WS_SYMBOLS[symbol]], depth=levels).map(
    to_book
  )


books: list[Book] = []
async with depth_stream('XBTUSD') as stream:
  async for book in stream:
    books.append(book)
    if len(books) >= 3:
      break
books


# %%
# not executed: Legacy account mapping is outside the current public Futures qualification.
# not executed: legacy Spot mapping updated for typing; public qualification is in market/public.py
async def rules(symbol: str, *, refetch: bool = False) -> Rules:
  """Map the public pair schedule to current combined SDK fees."""
  raw = await client.spot.market_data.asset_pairs(pair=symbol)
  pair = next(iter(raw.values()))
  fees_taker = pair.get('fees') or []
  fees_maker = pair.get('fees_maker') or fees_taker
  tick_size = pair.get('tick_size')
  ordermin = pair.get('ordermin')
  costmin = pair.get('costmin')
  return Rules(
    fee_asset=pair.get('quote', ''),
    tick_size=tick_size
    if tick_size is not None
    else Decimal(1) / 10 ** pair.get('pair_decimals', 0),
    step_size=Decimal(1) / 10 ** pair.get('lot_decimals', 0),
    fixed_min_qty=ordermin,
    min_value=costmin,
    fees=Fees.symmetric(
      maker=Decimal(str(min(fees_maker, key=lambda tier: tier[0])[1])) / 100,
      taker=Decimal(str(min(fees_taker, key=lambda tier: tier[0])[1])) / 100,
    )
    if fees_maker and fees_taker
    else None,
    api=pair.get('status') == 'online',
    details=pair,
  )


{symbol: await rules(symbol) for symbol in MARKETS['spot']}


# %%
# not executed: Legacy account mapping is outside the current public Futures qualification.
async def open_orders(symbol: str) -> list[OrderState]:
  raw = await client.spot.account.open_orders()
  out: list[OrderState] = []
  for txid, o in (raw.get('open') or {}).items():
    descr = o.get('descr') or {}
    if descr.get('pair') != symbol:
      continue
    vol = Decimal(o.get('vol', '0'))
    vol_exec = Decimal(o.get('vol_exec', '0'))
    sign = 1 if descr.get('type') == 'buy' else -1
    out.append(
      OrderState(
        id=txid,
        price=Decimal(descr.get('price', '0')),
        qty=sign * vol,
        filled_qty=sign * vol_exec,
        active=o.get('status') in ('pending', 'open'),
        details=o,
      )
    )
  return out


{symbol: await open_orders(symbol) for symbol in MARKETS['spot']}


# %%
# not executed: Legacy account mapping is outside the current public Futures qualification.
# not executed: legacy Spot mapping updated for typing; public qualification is in market/public.py
async def trades_history(symbol: str, start: datetime, end: datetime) -> list[Trade]:
  """Map account fills using the published quote asset."""
  pairs = await client.spot.market_data.asset_pairs(pair=symbol)
  quote = next(iter(pairs.values())).get('quote')
  if quote is None:
    raise ValueError('Kraken pair omitted its quote asset')
  raw = await client.spot.account.trades_history(
    pair=symbol,
    start=int(start.timestamp()),
    end=int(end.timestamp()),
  )
  out: list[Trade] = []
  for tid, t in (raw.get('trades') or {}).items():
    vol = Decimal(t.get('vol', '0'))
    sign = 1 if t.get('type') == 'buy' else -1
    fee_amt = Decimal(t.get('fee', '0') or '0')
    out.append(
      Trade(
        id=str(t.get('trade_id', tid)),
        price=Decimal(t.get('price', '0')),
        qty=sign * vol,
        time=t['time'],
        maker=bool(t.get('maker', False)),
        # Kraken's trades_history fee is denominated in the pair's quote asset, but doesn't
        # say so explicitly -- inferred from AssetPairs.
        fee=Trade.Fee(amount=fee_amt, asset=quote) if fee_amt else None,
        details=t,
      )
    )
  return out


end = datetime.now(timezone.utc)
start = end - timedelta(days=365)
{symbol: await trades_history(symbol, start, end) for symbol in MARKETS['spot']}


# %%
# not executed: Legacy account mapping is outside the current public Futures qualification.
async def trades_stream(symbol: str):
  ws_symbol = WS_SYMBOLS[symbol]
  async with client.streams.private.executions(snap_trades=False) as stream:
    async for msg in stream:
      for e in msg.get('data', []):
        # Subscript (not `.get()`) on `exec_type` so the type checker narrows
        # `e` from `ExecutionTradeEvent | ExecutionOrderEvent` down to
        # `ExecutionTradeEvent` for the rest of the loop body -- the trade-only
        # fields below (`last_qty`/`trade_id`/`last_price`/`side`) don't exist
        # at all on `ExecutionOrderEvent`.
        if e['exec_type'] != 'trade' or e.get('symbol') != ws_symbol:
          continue
        side = e['side']
        qty = Decimal(str(e['last_qty']))
        fees = e.get('fees') or []
        fee = (
          Trade.Fee(amount=Decimal(str(fees[0]['qty'])), asset=fees[0]['asset'])
          if fees
          else None
        )
        yield Trade(
          id=str(e['trade_id']),
          price=Decimal(str(e['last_price'])),
          qty=qty if side == 'buy' else -qty,
          time=e['timestamp'],
          maker=e.get('liquidity_ind') == 'm',
          fee=fee,
          details=e,
        )


stream = trades_stream('XBTUSD')
try:
  result = await asyncio.wait_for(anext(stream), timeout=5.0)
except asyncio.TimeoutError:
  result = 'no new trades observed in 5s (expected -- no live trading on this account)'
result


# %%
# not executed: Legacy account mapping is outside the current public Futures qualification.
# not executed: legacy Spot mapping updated for typing; public qualification is in market/public.py
async def position(symbol: str) -> Position:
  """Read the base asset balance for a spot pair."""
  pairs = await client.spot.market_data.asset_pairs(pair=symbol)
  base = next(iter(pairs.values())).get('base')
  if base is None:
    raise ValueError('Kraken pair omitted its base asset')
  balances = await client.spot.account.balance()
  size = Decimal(balances.get(base, '0'))
  return Position(size=size)


{symbol: await position(symbol) for symbol in MARKETS['spot']}


# %%
# not executed: Legacy account mapping is outside the current public Futures qualification.
# not executed: legacy Spot mapping updated for typing; public qualification is in market/public.py
async def collateral(symbol: str) -> Collateral:
  """Read the quote balance and native trade holds."""
  pairs = await client.spot.market_data.asset_pairs(pair=symbol)
  quote = next(iter(pairs.values())).get('quote')
  if quote is None:
    raise ValueError('Kraken pair omitted its quote asset')
  balances = await client.spot.account.balance_ex()
  info = balances.get(quote) or {}
  balance = Decimal(info.get('balance', '0'))
  hold = Decimal(info.get('hold_trade', '0'))
  return Collateral(equity=balance, free_collateral=balance - hold)


{symbol: await collateral(symbol) for symbol in MARKETS['spot']}


# %%
# not executed: Legacy account mapping is outside the current public Futures qualification.
async def available_notional(symbol: str) -> Decimal:
  c = await collateral(symbol)
  return c.free_collateral


{symbol: await available_notional(symbol) for symbol in MARKETS['spot']}


# %%
# not executed: Legacy account mapping is outside the current public Futures qualification.
async def place_order(
  symbol: str, order: Order, *, settings: Settings = {}
) -> OrderResponse:
  side: Literal['buy', 'sell'] = 'buy' if Decimal(order['qty']) > 0 else 'sell'
  volume = str(abs(Decimal(order['qty'])))
  price = str(Decimal(order['price']))
  body: AddOrderMarket | AddOrderLimit
  if order['type'] == 'MARKET':
    body = {'pair': symbol, 'type': side, 'ordertype': 'market', 'volume': volume}
  elif order['type'] == 'POST_ONLY':
    body = {
      'pair': symbol,
      'type': side,
      'ordertype': 'limit',
      'volume': volume,
      'price': price,
      'oflags': 'post',
    }
  else:
    body = {
      'pair': symbol,
      'type': side,
      'ordertype': 'limit',
      'volume': volume,
      'price': price,
    }
  raw = await client.spot.trading.add_order(body)
  return OrderResponse(id=(raw.get('txid') or [''])[0], details=raw)


# Not executed here -- would place a real order on the account.
await place_order(
  'XBTUSD', {'qty': Decimal('0.0001'), 'price': Decimal('20000'), 'type': 'LIMIT'}
)


# %%
# not executed: Legacy account mapping is outside the current public Futures qualification.
async def cancel_order(symbol: str, id: str, *, settings: Settings = {}):
  return await client.spot.trading.cancel_order(txid=id)


# Not executed here -- would cancel a real order on the account.
await cancel_order('XBTUSD', '123456')

# %% [markdown]
# ## Kraken Futures
#
# Public mappings now use released typed-kraken 0.4.0. See `market/futures.py` for the full qualification. Depth, rules, index and funding history are verified; next funding remains explicitly unsupported.

# %%
from tribulnation.kraken import KrakenMarket
from tribulnation.sdk.market import FundingRate, NextFunding
from datetime import datetime
from decimal import Decimal

futures_venue = await KrakenMarket.new(public=True).__aenter__()
futures_exchange = await futures_venue.exchange('perp')


# %%
async def depth(symbol: str, *, levels: int | None = None):
  """Requalify the formerly blocked method through typed-kraken 0.4.0 and the SDK."""
  return await (await futures_exchange.market(symbol)).depth(levels=levels)


{symbol: await depth(symbol) for symbol in ['PF_XBTUSD', 'PF_ETHUSD']}


# %%
async def rules(symbol: str, *, refetch: bool = False):
  """Requalify the formerly blocked method through typed-kraken 0.4.0 and the SDK."""
  return await (await futures_exchange.market(symbol)).rules(refetch=refetch)


{symbol: await rules(symbol) for symbol in ['PF_XBTUSD', 'PF_ETHUSD']}


# %%
async def index(symbol: str):
  """Requalify the formerly blocked method through typed-kraken 0.4.0 and the SDK."""
  return await (await futures_exchange.market(symbol)).index()


{symbol: await index(symbol) for symbol in ['PF_XBTUSD', 'PF_ETHUSD']}


# %%
async def next_funding(symbol: str) -> NextFunding:
  """No qualified native relative rate and settlement timestamp are published here."""
  return await (await futures_exchange.market(symbol)).next_funding()


try:
  await next_funding('PF_XBTUSD')
except NotImplementedError:
  print('Unsupported: native next-funding rate/time mapping remains unqualified')
else:
  raise AssertionError('next_funding must remain unsupported')


# %%
async def funding_rates(
  symbol: str, start: datetime | None = None, end: datetime | None = None
) -> list[FundingRate]:
  """Requalify historical relative rates at documented hour-end settlement times."""
  return list(await (await futures_exchange.market(symbol)).funding_rates(start, end))


{symbol: len(await funding_rates(symbol)) for symbol in ['PF_XBTUSD', 'PF_ETHUSD']}


# %% [markdown]
# ## Kraken Futures
#
# Public mappings now use released typed-kraken 0.4.0. See `market/futures.py` for the full qualification. Depth, rules, index and funding history are verified; next funding remains explicitly unsupported.

# %%
await futures_venue.__aexit__(None, None, None)
