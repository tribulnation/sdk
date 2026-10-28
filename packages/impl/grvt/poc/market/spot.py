# %% [markdown]
# # grvt `market` PoC (spot)
#
# Maps `typed_grvt` onto the SDK spot `market` surface, one method per cell, each executed live. The rules, and how a typed-client issue is reported in `typed-client-issues.md`, are in `.agents/skills/sdk-poc/SKILL.md`.
#
# **What GRVT spot is.** `SPOT_SWAP` instruments (`GRVT_USDT_SpotSwap`, `USDC_USDT_SpotSwap`) are listed with `venues == ['ORDERBOOK']`: ordinary central-limit-order-book instruments, traded with the same `create_order`, `orderbook`, `ticker`, `candlesticks` and `fill_history` endpoints as perpetuals. They are not RFQ (no instrument lists `RFQ`). GRVT's exchange contract (`gravity-technologies/exchange-contract`, `contracts/exchange/api/TradeContract.sol`, `_executeSpotOrder`) settles a spot fill in the trading sub-account's own **spot wallet** (`spotWalletBalances`), separate from its futures wallet: a buy spends quote and receives base less the fee (charged in base), a sell spends base and receives quote less the fee (charged in quote), and the trade reverts if either balance would go negative (`_requireSpotBalancesNonNegative`), so the spot wallet does not borrow. That is the SDK's spot exchange: one wallet, per-asset balances, `<account>:spot:<asset>` collateral IDs (ADR 0051).
#
# Two clients, neither able to sign an order:
#
# 1. `client`: **mainnet**, the read-only API key (`GRVT_API_KEY`, `GRVT_TRADING_ACCOUNT_ID`), no private key. Every account read runs here.
# 2. `testnet`: **testnet**, public (market data only), to compare the instrument lists. No testnet credentials are configured.
#
# Order placement and cancellation are written and never run (this PoC was not authorized to change state on either environment).

# %%
from collections import Counter
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from importlib.metadata import version
from typing_extensions import (
  Any,
  AsyncGenerator,
  AsyncIterable,
  Collection,
  Literal,
  Mapping,
  Sequence,
)
import asyncio
import os
import secrets

from dotenv import load_dotenv
from typed_grvt import BadRequest, Grvt
from typed_grvt.schemas import (
  Candlestick,
  CandlestickInterval,
  Fill,
  InstrumentDisplay,
  NewOrder,
  Order as GrvtOrder,
  OrderbookLevel,
  SpotBalance,
  Ticker as GrvtTicker,
)

from tribulnation.sdk.market import (
  Balance,
  Book,
  Candle,
  CandleInterval,
  Fees,
  Order,
  OrderResponse,
  OrderState,
  Settings,
  SpotBalances,
  SpotCollateralIds,
  SpotRules,
  Ticker,
  Trade,
)
from tribulnation.sdk.market.exchange import OverflowPolicy

load_dotenv()

stack = AsyncExitStack()
client = await stack.enter_async_context(
  Grvt.new(
    api_key=os.environ['GRVT_API_KEY'],
    trading_account_id=os.environ['GRVT_TRADING_ACCOUNT_ID'],
  )
)
testnet = await stack.enter_async_context(Grvt.new(env='testnet', public=True))

KIND: Literal['SPOT_SWAP'] = 'SPOT_SWAP'
GRVT = 'GRVT_USDT_SpotSwap'
USDC = 'USDC_USDT_SpotSwap'
MARKETS = [GRVT, USDC]
FEE_UNIT = Decimal('1e-6')
"""`ClientTier` fee rates are integers in millionths of notional, as for perpetuals."""

end = datetime.now(timezone.utc)
start = end - timedelta(days=7)


async def instruments(c: Grvt = client) -> dict[str, InstrumentDisplay]:
  """Every spot instrument, delisted ones included, keyed by instrument name."""
  return {i['instrument']: i for i in await c.market.all_instruments(kinds=[KIND])}


INSTRUMENTS = await instruments()
TESTNET_INSTRUMENTS = await instruments(testnet)
(
  version('typed-grvt'),
  {n: (i['venues'], i.get('status')) for n, i in INSTRUMENTS.items()},
  {n: (i['venues'], i.get('status')) for n, i in TESTNET_INSTRUMENTS.items()},
)

# %% [markdown]
# ## Surface
#
# What the client exposes. Widen or narrow the filter until every endpoint the mapping below uses is listed here.

# %%
from sdk_dev.surface import surface

print(
  surface(
    'typed_grvt',
    'Grvt',
    grep=r'^market\.(all_instruments|supported_assets|orderbook|ticker|candlesticks)|^market_streams\.orderbook|^trading\.(spot_account_summary|funding_account_summary|open_orders|order|create_order|cancel_order|cancel_all_orders|bulk_orders|fill_history)|^trading_streams\.fills',
  )
)


# %% [markdown]
# ## `markets`
#
# List available markets.
#
# Every `SPOT_SWAP` instrument, delisted ones included. A spot instrument shares its base and quote with a perpetual where one exists (`GRVT_USDT_Perp`), so every account filter below also carries `kind=['SPOT_SWAP']`.


# %%
async def markets(c: Grvt = client) -> Sequence[str]:
  """Every spot instrument's name."""
  return list(await instruments(c))


listed = await markets()
perps = {
  (i['base'], i['quote'])
  for i in await client.market.all_instruments(kinds=['PERPETUAL'])
}
{
  'mainnet': listed,
  'testnet': await markets(testnet),
  'venues': Counter(tuple(i['venues']) for i in INSTRUMENTS.values()),
  'base/quote shared with a perpetual': [
    n for n, i in INSTRUMENTS.items() if (i['base'], i['quote']) in perps
  ],
  'supported spot assets': [
    a['asset_code'] for a in (await client.market.supported_assets())['spot']
  ],
}


# %% [markdown]
# ## `depth`
#
# Fetch the market order book.
#
# The perpetual mapping unchanged: `orderbook` at the smallest of 10, 50, 100 or 500 levels per side covering `levels`.

# %%
DEPTHS: tuple[Literal[10, 50, 100, 500], ...] = (10, 50, 100, 500)


def venue_depth(levels: int | None) -> Literal[10, 50, 100, 500]:
  """The smallest venue depth covering `levels`, else the largest."""
  for d in DEPTHS:
    if levels is not None and d >= levels:
      return d
  return DEPTHS[-1]


def entries(levels: Sequence[OrderbookLevel]) -> list[Book.Entry]:
  """Book entries from venue levels."""
  return [Book.Entry(level['price'], level['size']) for level in levels]


async def depth(
  market_id: str, /, *, levels: int | None = None, settings: Settings = {}
) -> Book:
  """The aggregated book, at the smallest venue depth covering `levels`."""
  book = await client.market.orderbook(market_id, depth=venue_depth(levels))
  result = Book(
    bids=entries(book['bids']), asks=entries(book['asks']), time=book['event_time']
  )
  return result.limit(levels) if levels is not None else result


books = {m: await depth(m) for m in MARKETS}
{
  'full': {
    m: (len(b.bids), len(b.asks), b.best_bid.price, b.best_ask.price, b.time)
    for m, b in books.items()
  },
  'levels=3': await depth(GRVT, levels=3),
}


# %% [markdown]
# ## `depth_stream`
#
# Subscribe to the market order book.
#
# `v1.book.d`, as for perpetuals: the full book, then deltas every 50 ms.


# %%
@asynccontextmanager
async def depth_stream(
  market_id: str,
  /,
  *,
  levels: int | None = None,
  queue_size: int = 1,
  overflow: OverflowPolicy = 'latest',
  settings: Settings = {},
) -> AsyncGenerator[AsyncIterable[Book]]:
  """Maintain a local book from the snapshot and its deltas."""
  async with client.market_streams.orderbook_delta(market_id, rate=50) as stream:
    snapshots = stream.reply['num_snapshots'][0]

    async def books():
      book = Book()
      received = 0
      async for frame in stream:
        update = Book(
          bids=entries(frame['bids']),
          asks=entries(frame['asks']),
          time=frame['event_time'],
        )
        if received == 0:
          book = update
        else:
          book.update(update)
        received += 1
        if received >= snapshots:
          yield book.limit(levels) if levels is not None else book.copy()

    yield books()


async def stream_sample(market_id: str, seconds: float = 15) -> list[tuple[Any, ...]]:
  """The books streamed within `seconds` (deltas only arrive when the book changes)."""
  seen: list[tuple[Any, ...]] = []
  async with depth_stream(market_id) as stream:
    try:
      async with asyncio.timeout(seconds):
        async for update in stream:
          seen.append(
            (
              len(update.bids),
              len(update.asks),
              update.best_bid.price,
              update.best_ask.price,
              update.best_bid.price < update.best_ask.price,
            )
          )
    except TimeoutError:
      pass
  return seen


{
  m: {'books': len(s), 'first': s[0], 'last': s[-1], 'uncrossed': all(x[4] for x in s)}
  for m in MARKETS
  if (s := await stream_sample(m))
}


# %% [markdown]
# ## `tickers`
#
# Fetch a ticker snapshot for many markets at once.
#
# One `ticker` per instrument, as for perpetuals; 24 h volumes are taker buys plus sells.


# %%
def price_or_none(value: Decimal | None) -> Decimal | None:
  """A ticker price, or `None` where the venue sends `0` (an empty side) or nothing."""
  return value if value else None


def volume(buy: Decimal | None, sell: Decimal | None) -> Decimal | None:
  """Taker buy plus taker sell volume, or `None` if either is missing."""
  return None if buy is None or sell is None else buy + sell


def parse_ticker(t: GrvtTicker) -> Ticker:
  """An SDK ticker from a venue ticker."""
  bid = price_or_none(t.get('best_bid_price'))
  ask = price_or_none(t.get('best_ask_price'))
  return Ticker(
    last=price_or_none(t.get('last_price')),
    bid=bid,
    ask=ask,
    bid_qty=t.get('best_bid_size') if bid is not None else None,
    ask_qty=t.get('best_ask_size') if ask is not None else None,
    base_volume_24h=volume(t.get('buy_volume_24h_b'), t.get('sell_volume_24h_b')),
    quote_volume_24h=volume(t.get('buy_volume_24h_q'), t.get('sell_volume_24h_q')),
  )


async def tickers(
  markets: Collection[str] | None = None, *, settings: Settings = {}
) -> Mapping[str, Ticker]:
  """Tickers for the given markets, or every listed one."""
  names = [n for n in (INSTRUMENTS if markets is None else markets) if n in INSTRUMENTS]
  rows = await asyncio.gather(*[client.market.ticker(n, transport='ws') for n in names])
  return {n: parse_ticker(t) for n, t in zip(names, rows)}


{'all': await tickers(), 'empty': await tickers([])}


# %% [markdown]
# ## `rules`
#
# Fetch the market rules.
#
# From the instrument, as for perpetuals: `tick_size`, `min_size` (size step and minimum), `min_notional`; `api` is `status == 'ACTIVE'`. `base` and `quote` are the instrument's currency codes. `fee_asset` is `None`: the contract charges a buy's fee in base and a sell's in quote. `fees` is `None`: GRVT publishes no standard spot schedule the PoC could find (its help centre's fee page lists futures tiers), and the API reports only the configured account's tier.


# %%
async def rules(market_id: str, /, *, refetch: bool = False) -> SpotRules:
  """Increments, floors and the pair's assets."""
  i = (await instruments())[market_id] if refetch else INSTRUMENTS[market_id]
  return SpotRules(
    base=i['base'],
    quote=i['quote'],
    fee_asset=None,
    tick_size=i['tick_size'],
    step_size=i['min_size'],
    fixed_min_qty=i['min_size'],
    min_value=i['min_notional'],
    fees=None,
    api=i.get('status') == 'ACTIVE',
    details=i,
  )


{m: await rules(m) for m in MARKETS}


# %% [markdown]
# ## `fees`
#
# Fetch the selected market's account rates without a standard-rate fallback.
#
# The account's `ClientTier` carries `spot_maker_fee` and `spot_taker_fee` beside the futures rates, in the same millionths of notional (the schema says so for both). The mainnet account is tier 1 (spot maker 600, taker 850: 0.06% and 0.085%) and has no spot fill to cross-check the unit against a charged fee.


# %%
async def fees(market_id: str, /, *, refetch: bool = False, on: Grvt = client) -> Fees:
  """The account tier's spot maker and taker rates."""
  tier = (await on.trading.funding_account_summary())['tier']
  return Fees.symmetric(
    maker=tier['spot_maker_fee'] * FEE_UNIT, taker=tier['spot_taker_fee'] * FEE_UNIT
  )


async def tier_of(c: Grvt) -> dict[str, int]:
  """The tier and its spot and futures rate integers."""
  tier = (await c.trading.funding_account_summary())['tier']
  return {
    k: tier[k]
    for k in (
      'tier',
      'spot_maker_fee',
      'spot_taker_fee',
      'futures_maker_fee',
      'futures_taker_fee',
    )
  }


{
  'mainnet tier': await tier_of(client),
  'mainnet fees': await fees(GRVT),
}


# %% [markdown]
# ## `candles`
#
# Fetch the market's historical trade candles.
#
# `candlesticks_paged` with type `TRADE` (spot supports only `TRADE` and `MID`), exactly as for perpetuals.

# %%
INTERVALS: dict[CandleInterval, CandlestickInterval] = {
  '1m': 'CI_1_M',
  '5m': 'CI_5_M',
  '15m': 'CI_15_M',
  '1h': 'CI_1_H',
  '4h': 'CI_4_H',
  '1d': 'CI_1_D',
}


def parse_candle(c: Candlestick) -> Candle:
  """An SDK candle from a venue candlestick."""
  return Candle(
    time=c['open_time'],
    open=c['open'],
    high=c['high'],
    low=c['low'],
    close=c['close'],
    volume=c['volume_b'],
    quote_volume=c['volume_q'],
    trades=c['trades'],
  )


async def candles(
  market_id: str, /, interval: CandleInterval, start: datetime, end: datetime
):
  """Candles opening in `[start, end)`, newest first."""
  if end <= start:
    return
  pages = client.market.candlesticks_paged(
    market_id,
    interval=INTERVALS[interval],
    type='TRADE',
    start_time=start,
    end_time=end,
    limit=1000,
  )
  async for page in pages:
    rows = [parse_candle(c) for c in page if start <= c['open_time'] < end]
    if rows:
      yield rows


candle_end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
windows: list[tuple[CandleInterval, timedelta]] = [
  ('1h', timedelta(hours=5)),
  ('1d', timedelta(days=5)),
]
{
  m: {
    interval: [
      (c.time, c.close, c.volume, c.trades)
      async for page in candles(m, interval, candle_end - span, candle_end)
      for c in page
    ][:3]
    for interval, span in windows
  }
  for m in MARKETS
}


# %% [markdown]
# ## `query_order`
#
# Fetch the state of the order with the given ID.
#
# By client order id, as for perpetuals; an unknown id (`1004`) is `None`. The account has no spot order, so only the miss is exercised.

# %%
ACTIVE = {'PENDING', 'OPEN'}


def parse_order(o: GrvtOrder) -> OrderState:
  """An SDK order state from a single-leg venue order; sells are negative."""
  leg = o['legs'][0]
  sign = 1 if leg['is_buying_asset'] else -1
  state = o.get('state')
  traded = (state['traded_size'] if state is not None else None) or [Decimal(0)]
  return OrderState(
    id=o['metadata']['client_order_id'],
    price=leg.get('limit_price', Decimal(0)),
    qty=sign * leg['size'],
    filled_qty=sign * traded[0],
    active=state is not None and state['status'] in ACTIVE,
    details=o,
  )


async def query_order(
  market_id: str, /, id: str, *, on: Grvt = client
) -> OrderState | None:
  """Look the order up by client order id."""
  try:
    o = await on.trading.order({'client_order_id': id})
  except BadRequest as e:
    if e.args and e.args[0] == 1004:
      return None
    raise
  if o['legs'][0]['instrument'] != market_id:
    return None
  return parse_order(o)


def random_client_order_id() -> str:
  """A client order id in the range GRVT reserves for API clients, [2^63, 2^64)."""
  return str(2**63 + secrets.randbelow(2**63))


{
  'mainnet missing': await query_order(GRVT, random_client_order_id()),
}


# %% [markdown]
# ## `open_orders`
#
# Fetch your currently open orders.
#
# `open_orders` filtered by `kind=['SPOT_SWAP']`, base and quote: the kind keeps `GRVT_USDT_Perp`'s orders out of `GRVT_USDT_SpotSwap`'s.


# %%
def scope(market_id: str) -> tuple[list[str], list[str]]:
  """The base and quote filters naming one spot instrument (with its kind)."""
  i = INSTRUMENTS[market_id]
  return [i['base']], [i['quote']]


async def open_orders(market_id: str, /, *, on: Grvt = client) -> Sequence[OrderState]:
  """The market's open orders."""
  base, quote = scope(market_id)
  rows = await on.trading.open_orders(kind=[KIND], base=base, quote=quote)
  return [parse_order(o) for o in rows if o['legs'][0]['instrument'] == market_id]


{
  'mainnet': {m: await open_orders(m) for m in MARKETS},
  'spot orders, any instrument': len(await client.trading.open_orders(kind=[KIND])),
}


# %% [markdown]
# ## `trades_history`
#
# Fetch personal fills for one market or the whole exchange.
#
# `fill_history_paged` with `kind=['SPOT_SWAP']` (plus base and quote for one market), newest first; the perpetual mapping's fill parser and microsecond slack carry over. The account has no spot fill in the 90-day window, so this is `empty`.


# %%
def parse_fill(f: Fill) -> Trade:
  """An SDK trade from a venue fill; the fee is in `fee_currency` (base on a buy)."""
  return Trade(
    id=f['trade_id'],
    order_id=f['client_order_id'],
    client_order_id=f['client_order_id'],
    price=f['price'],
    qty=f['size'] if f['is_buyer'] else -f['size'],
    time=f['event_time'],
    maker=not f['is_taker'],
    fee=Trade.Fee(amount=f['fee'], asset=f['fee_currency']),
    details=f,
  )


async def trades_history(
  market_id: str | None, /, start: datetime, end: datetime, *, on: Grvt = client
) -> AsyncIterable[Sequence[Trade]]:
  """Personal spot fills between `start` and `end`, newest first."""
  if market_id is None:
    pages = on.trading.fill_history_paged(
      kind=[KIND], start_time=start, end_time=end, limit=1000
    )
  else:
    base, quote = scope(market_id)
    pages = on.trading.fill_history_paged(
      kind=[KIND], base=base, quote=quote, start_time=start, end_time=end, limit=1000
    )
  async for page in pages:
    yield [parse_fill(f) for f in page if market_id in (None, f['instrument'])]


history_start = end - timedelta(days=90)
scopes: list[str | None] = [*MARKETS, None]
{
  m: len([t async for page in trades_history(m, history_start, end) for t in page])
  for m in scopes
}


# %% [markdown]
# ## `trades_stream`
#
# Subscribe to your real-time trades.
#
# `v1.fill` for the instrument, as for perpetuals. Subscribes; no fill arrives (no orders are placed).


# %%
@asynccontextmanager
async def trades_stream(
  market_id: str,
  /,
  *,
  queue_size: int = 1000,
  overflow: OverflowPolicy = 'fail',
  settings: Settings = {},
  on: Grvt = client,
) -> AsyncGenerator[AsyncIterable[Trade]]:
  """The account's new fills on one market."""
  async with on.trading_streams.fills(instrument=market_id) as stream:

    async def trades():
      async for fill in stream:
        yield parse_fill(fill)

    yield trades()


async def first_trade(c: Grvt) -> Trade | str:
  """The first streamed fill within three seconds, else what happened."""
  async with trades_stream(GRVT, on=c) as stream:
    try:
      return await asyncio.wait_for(anext(aiter(stream)), 3)
    except asyncio.TimeoutError:
      return 'subscribed; no fill within 3 s'


await first_trade(client)


# %% [markdown]
# ## `balances`
#
# Fetch your base and quote balances.
#
# `spot_account_summary` of the trading sub-account lists the spot wallet's `spot_balances`, one row per held currency (none for a currency never held, which is zero). `total` is `balance`. `free` is `available_to_transfer`, the venue's figure for what can leave the wallet. Whether it excludes what open spot orders hold is **unverified**: the mainnet spot wallet is empty (no row at all), so the run shows only the call, its shape and the zero fallback. A held currency with an open spot order would settle it. Note this is the spot wallet; `account_summary`'s `spot_balances` is the futures wallet's cash (its `borrowed_amount` exists only there).


# %%
def spot_balance(rows: Sequence[SpotBalance], asset: str) -> Balance:
  """One currency's spot-wallet balance, zero when the wallet lists none."""
  for b in rows:
    if b['currency'] == asset:
      return Balance(total=b['balance'], free=b['available_to_transfer'])
  return Balance(total=Decimal(0), free=Decimal(0))


async def balances(market_id: str, /, *, on: Grvt = client) -> SpotBalances:
  """The pair's base and quote spot-wallet balances, from one summary."""
  i = INSTRUMENTS[market_id]
  rows = (await on.trading.spot_account_summary())['spot_balances']
  return SpotBalances(
    base=spot_balance(rows, i['base']), quote=spot_balance(rows, i['quote'])
  )


async def wallet_shape(c: Grvt) -> list[tuple[str, bool, bool]]:
  """Per held currency: whether it is non-zero and whether total equals free."""
  rows = (await c.trading.spot_account_summary())['spot_balances']
  return [
    (b['currency'], bool(b['balance']), b['balance'] == b['available_to_transfer'])
    for b in rows
  ]


{
  'mainnet rows (currency, held, balance == available)': await wallet_shape(client),
  'mainnet balances held': {
    m: (b.base.total > 0, b.quote.total > 0)
    for m in MARKETS
    if (b := await balances(m))
  },
}


# %% [markdown]
# ## `balance`
#
# One asset's spot-wallet balance, by currency code, from the same summary.


# %%
async def balance(asset: str, /, *, on: Grvt = client) -> Balance:
  """One currency's spot-wallet balance."""
  return spot_balance((await on.trading.spot_account_summary())['spot_balances'], asset)


{a: (await balance(a)).total >= 0 for a in ('USDT', 'USDC', 'GRVT', 'NOPE')}


# %% [markdown]
# ## `collateral_ids`
#
# The collateral IDs a market's orders reserve on: `<account>:spot:<asset>` (ADR 0051), the spot wallet's base and quote. Pure: no request.


# %%
async def collateral_ids(
  market_id: str, /, *, account_id: str = 'grvt'
) -> SpotCollateralIds:
  """The pair's assets in the spot wallet."""
  i = INSTRUMENTS[market_id]
  return SpotCollateralIds(
    base=f'{account_id}:spot:{i["base"]}', quote=f'{account_id}:spot:{i["quote"]}'
  )


{m: await collateral_ids(m) for m in MARKETS}


# %% [markdown]
# ## `place_order`
#
# Place an order in the market.
#
# The perpetual mapping applies unchanged, with the spot instrument as the leg's `instrument` (the contract's spot path takes the same signed single-leg order; `reduce_only`, TPSL and vault sub-accounts are refused, and the SDK sends none). Not executed: this PoC may not change state.


# %%
def new_order(market_id: str, order: Order, client_order_id: str) -> NewOrder:
  """The venue order for an SDK order, as for perpetuals."""
  qty = Decimal(str(order['qty']))
  if order['type'] == 'MARKET':
    return {
      'is_market': True,
      'time_in_force': 'IMMEDIATE_OR_CANCEL',
      'metadata': {'client_order_id': client_order_id},
      'legs': [{'instrument': market_id, 'size': abs(qty), 'is_buying_asset': qty > 0}],
    }
  return {
    'time_in_force': 'GOOD_TILL_TIME',
    'post_only': order['type'] == 'POST_ONLY',
    'metadata': {'client_order_id': client_order_id},
    'legs': [
      {
        'instrument': market_id,
        'size': abs(qty),
        'limit_price': Decimal(str(order['price'])),
        'is_buying_asset': qty > 0,
      }
    ],
  }


async def place_order(
  market_id: str, /, order: Order, *, settings: Settings = {}
) -> OrderResponse:
  """Sign and send the order; its client order id is the SDK id."""
  client_order_id = order.get('client_order_id') or random_client_order_id()
  reply = await client.trading.create_order(
    new_order(market_id, order, client_order_id)
  )
  return OrderResponse(id=client_order_id, details=reply)


# not executed: changes the account
await place_order(
  GRVT, {'type': 'POST_ONLY', 'qty': Decimal('1'), 'price': Decimal('0.01')}
)


# %% [markdown]
# ## `cancel_order`
#
# Cancel an order in the market. By client order id, as for perpetuals.


# %%
async def cancel_order(market_id: str, /, id: str, *, settings: Settings = {}) -> Any:
  """Cancel by client order id."""
  return await client.trading.cancel_order({'client_order_id': id})


# not executed: changes the account
await cancel_order(GRVT, '<order id>')


# %% [markdown]
# ## `cancel_orders`
#
# Cancel multiple orders in the market. `bulk_orders` by client order ids, as for perpetuals.


# %%
async def cancel_orders(
  market_id: str, /, ids: Sequence[str], *, settings: Settings = {}
) -> Any:
  """Cancel by client order ids."""
  return await client.trading.bulk_orders({'client_order_i_ds': list(ids)})


# not executed: changes the account
await cancel_orders(GRVT, ['<order id>'])


# %% [markdown]
# ## `cancel_open_orders`
#
# Cancel all open orders in the market: the venue's cancel-all scoped by `kind=['SPOT_SWAP']`, base and quote.


# %%
async def cancel_open_orders(market_id: str, /, *, settings: Settings = {}) -> Any:
  """The venue's cancel-all, scoped to the spot instrument."""
  base, quote = scope(market_id)
  return await client.trading.cancel_all_orders(kind=[KIND], base=base, quote=quote)


# not executed: changes the account
await cancel_open_orders(GRVT)

# %% [markdown]
# ## Coverage
#
# Status is one of `verified` (executed live, real data), `empty` (executed live, nothing to show on this account), `blocked` (a typed-client issue, numbered in `typed-client-issues.md`), `not supported` (the venue has no such data) or `not attempted`.
#
# | method | status | note |
# |---|---|---|
# | `markets` | verified | `SPOT_SWAP` instruments, all `ORDERBOOK` |
# | `depth` | verified | |
# | `depth_stream` | verified | |
# | `tickers` | verified | |
# | `rules` | verified | `fees` `None`: no published standard spot schedule; `fee_asset` `None` (base on a buy, quote on a sell) |
# | `fees` | verified | the tier's `spot_*_fee`; unit not cross-checked against a spot fill |
# | `candles` | verified | |
# | `query_order` | empty | miss only; a spot order on the account would populate it |
# | `open_orders` | empty | a resting spot order would populate it |
# | `trades_history` | empty | a spot fill would populate it |
# | `trades_stream` | empty | subscribed; a spot fill would populate it |
# | `balances` | empty | the spot wallet lists no currency; a held currency (and an open spot order, to check that `available_to_transfer` excludes its hold) would populate it |
# | `balance` | empty | as `balances` |
# | `collateral_ids` | verified | `<account>:spot:<asset>`, no request |
# | `place_order` | not attempted | not authorized to change state; perpetual mapping with a spot instrument |
# | `cancel_order` | not attempted | as above |
# | `cancel_orders` | not attempted | as above |
# | `cancel_open_orders` | not attempted | as above |

# %% [markdown]
# ## Catalogue
#
# Every ID the verified methods returned, minus what the catalogue translates for this platform. Anything listed is a catalogue addition to make, not something to rename here: the SDK emits venue-native IDs and the catalogue maps them.

# %%
from sdk_dev.catalogue import Ids, gap, load_catalogue

assets = {a for i in INSTRUMENTS.values() for a in (i['base'], i['quote'])}
ids = Ids(spot_markets=set(listed), assets=assets)
gap('grvt', ids, load_catalogue())

# %% [markdown]
# ## Cleanup

# %%
await stack.aclose()
