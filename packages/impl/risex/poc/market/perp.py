# %% [markdown]
# # risex `market` PoC
#
# Maps `typed_risex` onto the SDK `market` surface, one method per cell, each executed live. The rules, and how a typed-client issue is reported in `typed-client-issues.md`, are in `.agents/skills/sdk-poc/SKILL.md`.
#
# RISEx is an on-chain perpetuals DEX: every market is a USDC-margined perpetual, addressed by its numeric `market_id`. There are no API keys: account reads are public and keyed by the account's address; trading signs EIP-712 permits with a registered signer key, and a few reads (`account.fees`) need a JWT the client logs in for with a key. Public data and address reads run against:
#
# - **mainnet** (`client`, public, no credentials: mainnet trading is invite-only and there is no mainnet key), with public, active trader addresses taken from the 24h volume leaderboard, whose reads are displayed as shapes and counts only;
# - **testnet** (`testnet`, `RISEX_TESTNET_*`: a faucet-funded throwaway account with a registered signer), for the key-gated reads (fees, fills stream) and the account's own history.
#
# Market IDs are `market_id` as a decimal string (`'1'` BTC/USDC on both networks). Names are not unique (two `DOGE/USDC` on mainnet, three `AAVE/USDC` on testnet), so they cannot be the ID. The one collateral, fee and funding asset is USDC.

# %%
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from importlib.metadata import version
from typing_extensions import (
  Any,
  AsyncGenerator,
  AsyncIterable,
  Collection,
  Mapping,
  Sequence,
)
import asyncio
import os

from dotenv import load_dotenv
from typed_risex import RISEx, BadRequest as RisexBadRequest
from typed_risex.account.trade_history import AccountTrade
from typed_risex.markets.all import MarketInfo
from typed_risex.schemas import LimitOrderRequest
from typed_risex.streams.fills import StreamFill

from tribulnation.sdk.market import (
  Book,
  Candle,
  CandleInterval,
  Fees,
  FundingPayment,
  FundingRate,
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
from tribulnation.sdk.market.types.candles import candle_width

load_dotenv()

stack = AsyncExitStack()
client = await stack.enter_async_context(RISEx.new(network='mainnet', public=True))
"""Mainnet, public: market data and third-party traders' public reads."""
testnet = await stack.enter_async_context(
  RISEx.new(
    network='testnet',
    account_key=os.environ['RISEX_TESTNET_ACCOUNT_KEY'],
    signer_key=os.environ['RISEX_TESTNET_SIGNER_KEY'],
  )
)
"""Testnet, signing: the funded account's reads, its JWT reads and fills stream."""
ME = os.environ['RISEX_TESTNET_ADDRESS']
"""The testnet account's address."""
TRADER = '0x7079b5814032C0b02425135F06F32A0084cdf2d2'
"""A public mainnet trader (24h volume leaderboard rank 3 on 2026-11-17): positions on
many markets, no resting orders. Only shapes and counts of its reads are displayed."""
MAKER = '0x36Dc0d99DCaEe443cEbaa5FB8c11877d157C26df'
"""A public mainnet market maker (leaderboard rank 1): hundreds of resting orders."""

MARKETS = ['1', '2', '4']
"""BTC/USDC, ETH/USDC and SOL/USDC, on both networks."""
USDC = 'USDC'
"""The collateral asset: margin, PnL, trading fees and funding all settle in it."""
WAD = Decimal(10**18)
"""The scale of the on-chain integers some endpoints return (`account.positions`)."""
NS = 10**9
"""Nanoseconds per second: candle intervals are nanosecond durations."""

end = datetime.now(timezone.utc)
start = end - timedelta(days=7)


async def market_table(on: RISEx = client, *, refresh: bool = False) -> dict[str, MarketInfo]:
  """Every market of the deployment, by `market_id` as a string."""
  rows = (await on.markets.all(refresh or None))['markets']
  return {str(m['market_id']): m for m in rows}


def listed(table: Mapping[str, MarketInfo]) -> list[str]:
  """The markets that trade: enabled off-chain (`active`) and unlocked on-chain.

  Mainnet's deprecated `DOGE/USDC` (13) is inactive; testnet's stale markets (the
  deprecated DOGE, LINK, LTC, ...) are locked, with a funding time frozen in the past.
  """
  return [mid for mid, m in table.items() if m['active'] and m['config']['unlocked']]


details = await market_table()
testnet_details = await market_table(testnet)
{
  'typed-risex': version('typed-risex'),
  'mainnet markets': len(details),
  'mainnet listed': len(listed(details)),
  'testnet markets': len(testnet_details),
  'testnet listed': len(listed(testnet_details)),
  'names': {mid: details[mid]['config']['name'] for mid in MARKETS},
}

# %% [markdown]
# ## Surface
#
# What the client exposes. Widen or narrow the filter until every endpoint the mapping below uses is listed here.

# %%
from sdk_dev.surface import surface

print(
  surface(
    'typed_risex',
    'RISEx',
    grep=r'markets\.|orderbook|fills|expected_funding|orders\.(place|cancel|get|open|history)|account\.(position|fees|trade_history|funding_payments|cross_margin)|portfolio\.details',
  )
)


# %% [markdown]
# ## `markets`
#
# `markets.all`: every market with its configuration and live statistics. Listed: `active` (the off-chain switch) and `config.unlocked` (on-chain). IDs are `market_id` strings.

# %%
async def markets(on: RISEx = client) -> Sequence[str]:
  return listed(await market_table(on))


{'mainnet': await markets(), 'testnet': await markets(testnet)}


# %% [markdown]
# ## `depth`
#
# `markets.orderbook`: aggregated levels, best first, at most 250 per side (the documented `limit` cap), with no timestamp.

# %%
BOOK_LIMIT = 250


async def depth(market_id: str, /, *, levels: int | None = None, settings: Settings = {}) -> Book:
  limit = min(levels, BOOK_LIMIT) if levels is not None else BOOK_LIMIT
  raw = await client.markets.orderbook(market_id=int(market_id), limit=limit)
  return Book(
    bids=[Book.Entry(r['price'], r['quantity']) for r in raw['bids']],
    asks=[Book.Entry(r['price'], r['quantity']) for r in raw['asks']],
  )


{m: await depth(m, levels=3) for m in MARKETS}


# %% [markdown]
# ## `depth_stream`
#
# `streams.orderbook([market])`: a snapshot (sent before the subscribe ack), then per-block level updates whose `quantity` is the level's absolute size (`0` deletes it), stamped with `worker_timestamp`. Updates carry a CRC32 checksum of the whole book, computed over 1e18-scaled integers in an undocumented layout, and no sequence number. A client holds one subscription per channel, so each market's stream gets its own (public) client and connection.

# %%
@asynccontextmanager
async def depth_stream(market_id: str, /, *, levels: int | None = None, queue_size: int = 1, overflow: OverflowPolicy = 'latest', settings: Settings = {}) -> AsyncGenerator[AsyncIterable[Book]]:
  async with RISEx.new(network='mainnet', public=True) as own:
    async with own.streams.orderbook([int(market_id)]) as stream:

      async def books():
        book = Book()
        async for frame in stream:
          data = frame['data']
          change = Book(
            bids=[Book.Entry(r['price'], r['quantity']) for r in data['bids']],
            asks=[Book.Entry(r['price'], r['quantity']) for r in data['asks']],
            time=frame['worker_timestamp'],
          )
          if frame['type'] == 'snapshot':
            book = change
          else:
            book.update(change)
          yield book.frozen().limit(levels) if levels else book.frozen()

      yield books()


frames: list[Book] = []
async with depth_stream(MARKETS[0], levels=2) as stream:
  async for update in stream:
    frames.append(update)
    if len(frames) == 4:
      break
frames


# %% [markdown]
# ## `tickers`
#
# `markets.all`, refreshed (`force_refresh`; otherwise served from a 5-minute cache): `last_price` and `quote_volume_24h`. The venue publishes no best bid/ask in it and no base volume, so those stay `None`.

# %%
async def tickers(markets: Collection[str] | None = None, *, settings: Settings = {}, ttl: timedelta | None = None) -> Mapping[str, Ticker]:
  table = await market_table(refresh=True)
  wanted = listed(table) if markets is None else [m for m in listed(table) if m in markets]
  return {
    m: Ticker(last=table[m]['last_price'], quote_volume_24h=table[m]['quote_volume_24h'])
    for m in wanted
  }


await tickers(MARKETS)


# %% [markdown]
# ## `rules`
#
# `config`: `step_price` is the tick, `step_size` the step, `min_order_size` the minimum. Orders are sent in integer ticks and steps, so an off-grid price or size cannot be expressed. `match_price_band` (`0.05`, `0.02`) is undocumented (neither its unit nor its reference price is stated; a bid 20% over the mark reverted with `OrderPriceOutsideMatchBand(price, low, high)`, the bounds about ±5% of the mark), so it stays in `details` rather than becoming a relative price bound. The fee schedule is only served to a logged-in account (`account.fees`), so `fees` is `None`. `api`: listed and not reduce-only.

# %%
async def rules(market_id: str, /, *, refetch: bool = False) -> Rules:
  m = details[market_id]
  config = m['config']
  return Rules(
    fee_asset=USDC,
    tick_size=config['step_price'],
    step_size=config['step_size'],
    fixed_min_qty=config['min_order_size'],
    fees=None,
    api=market_id in listed(details) and not m['reduce_only'],
    details={
      'name': config['name'],
      'max_leverage': config['max_leverage'],
      'match_price_band': config['match_price_band'],
      'max_position_size': m['max_position_size'],
      'post_only': m['post_only'],
      'reduce_only': m['reduce_only'],
    },
  )


{m: await rules(m) for m in MARKETS}


# %% [markdown]
# ## `fees`
#
# `account.fees` (JWT, so it needs a key; testnet): the account's current tier, `taker_bps`/`maker_bps` in basis points, a negative maker rate being a rebate. One rate per role, for every market and side. The bps are declared `float`; `str()` gives back the venue's decimal (`2.0`, `-0.5`).

# %%
async def fees(market_id: str, /, *, refetch: bool = False, on: RISEx = testnet) -> Fees:
  row = await on.account.fees()
  bps = Decimal(10_000)
  return Fees.symmetric(maker=Decimal(str(row['maker_bps'])) / bps, taker=Decimal(str(row['taker_bps'])) / bps)


{m: await fees(m) for m in MARKETS}


# %% [markdown]
# ## `candles`
#
# `markets.candles`: `interval` is a nanosecond duration. Measured on mainnet (2026-11-17): `1m`, `5m`, `15m`, `1h`, `4h`, `1d` (and `1w`) are served at their width; other widths (`3m`, `30m`, `2h`, ...) silently come back as 1-minute candles, so only the served ones are mapped. A range starting at `from` returns candles opening at or after it and before `to` (00:00 to 05:00 hourly gave 00:00..04:00). One request returns the whole range, but the venue rejects ranges over 86,400 intervals, so the walk splits the window into chunks of `CANDLES_CHUNK` intervals. `volume` is base volume.

# %%
CANDLE_SECONDS: Mapping[CandleInterval, int] = {'1m': 60, '5m': 300, '15m': 900, '1h': 3600, '4h': 14400, '1d': 86400}
CANDLES_CHUNK = 10_000


async def candles(market_id: str, /, interval: CandleInterval, start: datetime, end: datetime):
  width = candle_width(interval)
  lower = start
  while lower < end:
    upper = min(lower + width * CANDLES_CHUNK, end)
    raw = await client.markets.candles(market_id=int(market_id), interval=CANDLE_SECONDS[interval] * NS, from_=lower, to=upper)
    rows = [Candle(time=c['time'], open=c['open'], high=c['high'], low=c['low'], close=c['close'], volume=c['volume']) for c in raw['data'] if lower <= c['time'] < upper]
    if rows:
      yield rows
    lower = upper


day = datetime(2026, 11, 10, tzinfo=timezone.utc)
{
  i: (len(rows := [c async for page in candles('1', i, day, day + candle_width(i) * 5) for c in page]), rows[:1])
  for i in CANDLE_SECONDS
}


# %% [markdown]
# ## `query_order`
#
# `orders.get` by order id (`0x` + 48 hex digits, which `orders.place` returns): open, filled or cancelled. An unknown id answers `NotFound: order not found` (`BadRequest`), read as `None`. The order's `size` is the original size and `filled_size` what filled, both unsigned beside `side`. Active is `ORDER_STATUS_OPEN`. Testnet, the account's latest order.

# %%
async def query_order(market_id: str, /, id: str, on: RISEx = testnet) -> OrderState | None:
  try:
    o = (await on.orders.get(id, market_id=int(market_id)))['order']
  except RisexBadRequest as e:
    if e.args and e.args[0] == 'NotFound':
      return None
    raise
  sign = -1 if o['side'] == 'SELL' else 1
  return OrderState(id=o['id'], price=o['price'], qty=o['size'] * sign, filled_qty=o['filled_size'] * sign, active=o['status'] == 'ORDER_STATUS_OPEN', details=o)


latest = (await testnet.orders.history(account=ME, market_id=1, limit=1))['orders'][0]
{
  'latest': await query_order('1', latest['id']),
  'unknown': await query_order('1', '0x000000000000000100000000038ffd2d0000000000000194'),
}


# %% [markdown]
# ## `open_orders`
#
# `orders.open` (on-chain state; one reply holds every resting order, `limit`/`start_index` have no effect): `size_steps`/`price_ticks` in the market's increments, `side` `0` buy / `1` sell. It carries no fill progress, so each order's `filled_size` comes from `orders.history` with `statuses=['ORDER_STATUS_OPEN']` (the indexer), which listed a just-placed order at once on testnet. Mainnet market maker: counts only.

# %%
async def open_orders(market_id: str, /, on: RISEx = client, account: str = MAKER) -> Sequence[OrderState]:
  config = (details if on is client else testnet_details)[market_id]['config']
  rows = (await on.orders.open(account=account, market_id=int(market_id)))['orders']
  indexed = {o['id']: o for o in await on.orders.history_paged(account=account, market_id=int(market_id), statuses=['ORDER_STATUS_OPEN'], limit=1000)}
  out: list[OrderState] = []
  for o in rows:
    sign = -1 if o['side'] == 1 else 1
    known = indexed.get(o['order_id'])
    filled = known['filled_size'] if known is not None else Decimal(0)
    out.append(OrderState(id=o['order_id'], price=o['price_ticks'] * config['step_price'], qty=o['size_steps'] * config['step_size'] * sign, filled_qty=filled * sign, active=True, details=o))
  return out


maker_orders = {m: await open_orders(m) for m in MARKETS}
{m: (len(rows), sum(1 for r in rows if r.id in {o.id for o in rows}), sum(1 for r in rows if r.filled_qty)) for m, rows in maker_orders.items()}


# %% [markdown]
# ## `trades_history`
#
# `account.trade_history_paged`, newest first with `start_time`/`end_time` filters; per market or exchange-wide (`market_id` omitted). `size` is unsigned beside `side`, `fee` in USDC, paid-positive; `liquidity_indicator` gives the role; `client_order_id` is `''` for an order placed without one. Testnet: the account's own fills.

# %%
def parse_trade(t: AccountTrade | StreamFill) -> Trade:
  return Trade(
    id=t['id'],
    order_id=t['order_id'],
    client_order_id=t.get('client_order_id') or None,
    price=t['price'],
    qty=-t['size'] if t['side'] == 'SELL' else t['size'],
    time=t['time'],
    maker=t['liquidity_indicator'] == 'MAKER',
    fee=Trade.Fee(amount=t['fee'], asset=USDC),
    details=t,
  )


async def trades_history(market_id: str | None, /, start: datetime, end: datetime, on: RISEx = testnet, account: str = ME) -> AsyncIterable[Sequence[Trade]]:
  pages = on.account.trade_history_paged(account, market_id=None if market_id is None else int(market_id), start_time=start, end_time=end, limit=1000)
  async for page in pages:
    yield [parse_trade(t) for t in page]


fills = [t async for page in trades_history('1', end - timedelta(days=2), datetime.now(timezone.utc)) for t in page]
{
  'testnet BTC fills': len(fills),
  'first': fills[:1],
  'testnet all markets': len([t async for page in trades_history(None, start, end) for t in page]),
  'mainnet trader (count)': len([t async for page in trades_history('1', end - timedelta(days=1), end, on=client, account=TRADER) for t in page]),
}


# %% [markdown]
# ## `trades_stream`
#
# `streams.fills`: the account's fills, authenticated with the signer key (unavailable without one), rows shaped like `account.trade_history` (`client_order_id` absent when the order had none). One subscription per channel per client, so the adapter subscribes every market once and filters. Testnet: no fill happens while this cell waits, so it shows the subscription only; fills were observed on this channel while the lifecycle probe traded (an IOC buy's fill carried its `client_order_id` `4343`).

# %%
@asynccontextmanager
async def trades_stream(market_id: str, /, *, queue_size: int = 1000, overflow: OverflowPolicy = 'fail', settings: Settings = {}) -> AsyncGenerator[AsyncIterable[Trade]]:
  async with testnet.streams.fills() as stream:

    async def trades():
      async for frame in stream:
        if str(frame['market_id']) == market_id:
          yield parse_trade(frame['data'])

    yield trades()


async with trades_stream(MARKETS[0]) as stream:
  try:
    first = await asyncio.wait_for(anext(aiter(stream)), timeout=5)
  except TimeoutError:
    first = None
first


# %% [markdown]
# ## `place_order`
#
# `orders.place` signs a permit with the signer key; sizes and prices are integer steps and ticks, so an off-grid order raises before signing. Mapping: `LIMIT` is a GTC limit (`order_type 1`), `POST_ONLY` a GTC limit with `post_only`, `MARKET` an IOC limit at `price` (`order_type 1`, `time_in_force 3`). Not the venue's market order (`order_type 0`): on testnet a market buy priced 3% under the bid filled above the bid, so its `price_ticks` does not bound the fill, while an IOC limit at the same price came back `Order not filled` (`filled_quantity` 0) and one priced through the ask filled at the ask. `client_order_id` is an integer on the wire (a uint, echoed back as a decimal string). The reply is synchronous (the transaction is mined): `filled_quantity` (1e18-scaled) is reported for IOC orders only. A reverted placement answers `FailedPrecondition` (`PostOnlyOrderMatched()` for a crossing post-only, `OrderPriceOutsideMatchBand` beyond the band): nothing rests.

# %%
async def place_order(market_id: str, /, order: Order, *, settings: Settings = {}) -> OrderResponse:
  config = testnet_details[market_id]['config']
  qty, price = Decimal(order['qty']), Decimal(order['price'])
  request: LimitOrderRequest = {
    'market_id': int(market_id),
    'order_type': 1,
    'side': 0 if qty > 0 else 1,
    'size_steps': int(abs(qty) / config['step_size']),
    'price_ticks': int(price / config['step_price']),
  }
  if order['type'] == 'POST_ONLY':
    request['post_only'] = True
  if order['type'] == 'MARKET':
    request['time_in_force'] = 3
  if (client_id := order.get('client_order_id')) is not None:
    request['client_order_id'] = int(client_id)
  placed = await testnet.orders.place(request)
  filled = placed['filled_quantity']
  return OrderResponse(id=placed['order_id'], details=placed, filled_qty=None if filled == '' else Decimal(filled) / WAD)


# not executed: state-changing; the lifecycle is verified on testnet through the implementation
bid = testnet_details['1']['mark_price'] * Decimal('0.8')
await place_order('1', {'type': 'POST_ONLY', 'qty': Decimal('0.0001'), 'price': bid.quantize(Decimal('0.1'))})


# %% [markdown]
# ## `cancel_order`
#
# `orders.cancel(market_id, order_id=...)`, signed and mined synchronously. An order no longer open answers `InvalidArgument` (`order <n> is not open (status: 3)`, or `order is already filled or cancelled` for an unknown id): `OrderNotFound`.

# %%
async def cancel_order(market_id: str, /, id: str, *, settings: Settings = {}) -> Any:
  return await testnet.orders.cancel(int(market_id), order_id=id)


# not executed: state-changing; the lifecycle is verified on testnet through the implementation
await cancel_order('1', '<order id>')


# %% [markdown]
# ## `cancel_orders`
#
# The SDK default: one `cancel_order` per id. The venue has no batch cancel by id.

# %%
async def cancel_orders(market_id: str, /, ids: Sequence[str], *, settings: Settings = {}) -> Any:
  return [await cancel_order(market_id, id) for id in ids]


# not executed: state-changing; the lifecycle is verified on testnet through the implementation
await cancel_orders('1', ['<order id>'])


# %% [markdown]
# ## `replace_order`
#
# The SDK default (cancel, then place): RISEx has no modify.

# %%
async def replace_order(market_id: str, /, id: str, order: Order, *, settings: Settings = {}) -> OrderResponse:
  await cancel_order(market_id, id)
  return await place_order(market_id, order)


# not executed: state-changing; the SDK default over place and cancel
await replace_order('1', '<order id>', {'type': 'LIMIT', 'qty': Decimal('0'), 'price': Decimal('0')})


# %% [markdown]
# ## `replace_orders`
#
# The SDK default: one `replace_order` per pair.

# %%
async def replace_orders(market_id: str, /, orders: Sequence[tuple[str, Order]], *, settings: Settings = {}) -> Sequence[OrderResponse | Exception]:
  return [await replace_order(market_id, id, order) for id, order in orders]


# not executed: state-changing; the SDK default over place and cancel
await replace_orders('1', [])


# %% [markdown]
# ## `cancel_open_orders`
#
# `orders.cancel_all(market_id)`: every resting order of the account in the market, in one signed transaction (TP/SL orders are off-chain and separate). Verified in the lifecycle probe: three resting post-only bids cancelled, `orders.open` empty after.

# %%
async def cancel_open_orders(market_id: str, /, *, settings: Settings = {}) -> Any:
  return await testnet.orders.cancel_all(int(market_id))


# not executed: state-changing; the lifecycle is verified on testnet through the implementation
await cancel_open_orders('1')


# %% [markdown]
# ## `index`
#
# `markets.all(force_refresh=True, market_ids=[...])`: `index_price`, the oracle's.

# %%
async def index(market_id: str, /, *, settings: Settings = {}):
  return (await client.markets.all(True, market_ids=[int(market_id)]))['markets'][0]['index_price']


{m: await index(m) for m in MARKETS}


# %% [markdown]
# ## `next_funding`
#
# The `expected_funding_rate` stream's first frame: the venue's estimate of the next hourly rate and its time. Not `markets.all`'s `current_funding_rate`: it equals the rate last *applied* (mainnet BTC, 2026-11-17: `0.000033634047918834`, the `funding_rate_history` record ending 10:00, while the stream estimated `0.0000239` for 11:00). Funding is hourly (`funding_interval` 3600 s, in nanoseconds); a positive rate is paid by longs (see `funding_payments`). The stream is public; one client per call, since a client holds one subscription per channel.

# %%
FUNDING_INTERVAL = timedelta(hours=1)


async def expected_funding(market_ids: Collection[str]) -> dict[str, NextFunding]:
  async with RISEx.new(network='mainnet', public=True) as own:
    async with own.streams.expected_funding_rate([int(m) for m in market_ids]) as stream:
      async for frame in stream:
        return {
          str(r['market_id']): NextFunding(rate=r['estimated_rate'], time=r['next_funding_time'], interval=FUNDING_INTERVAL)
          for r in frame['data']
        }
  raise RuntimeError('stream closed')


async def next_funding(market_id: str, /, *, ttl: timedelta | None = None) -> NextFunding:
  return (await expected_funding([market_id]))[market_id]


{m: await next_funding(m) for m in MARKETS}


# %% [markdown]
# ## `perp_stats`
#
# `markets.all` (refreshed) for index, mark and open interest, plus one `expected_funding_rate` frame for the predicted rate and time. `open_interest`'s unit is undocumented; BTC's `250.800606` against a 24h quote volume of 39.4M USDC reads as base units (250 BTC, about 16M USDC), not USDC.

# %%
async def perp_stats(markets: Collection[str] | None = None, *, settings: Settings = {}, ttl: timedelta | None = None) -> Mapping[str, PerpStats]:
  table = await market_table(refresh=True)
  wanted = listed(table) if markets is None else [m for m in listed(table) if m in markets]
  funding = await expected_funding(wanted)
  return {
    m: PerpStats(
      index=table[m]['index_price'],
      mark=table[m]['mark_price'],
      funding=funding[m].rate if m in funding else None,
      next_funding_time=funding[m].time if m in funding else None,
      funding_interval=FUNDING_INTERVAL,
      open_interest=table[m]['open_interest'],
    )
    for m in wanted
  }


every = await perp_stats()
{'count': len(every), 'with funding': sum(1 for s in every.values() if s.funding is not None), 'BTC': every['1']}


# %% [markdown]
# ## `funding_rates`
#
# `markets.funding_rate_history_paged`: one settlement an hour, newest first, `funding_rate` the hourly rate applied, stamped with the settlement time (`end_time`, which equals `block_time`). Bounds are filtered locally inclusive.

# %%
async def funding_rates(market_id: str, /, start: datetime | None = None, end: datetime | None = None):
  pages = client.markets.funding_rate_history_paged(market_id=int(market_id), start_time=start, end_time=end, limit=1000)
  async for page in pages:
    yield [FundingRate(rate=r['funding_rate'], time=r['end_time']) for r in page if (start is None or r['end_time'] >= start) and (end is None or r['end_time'] <= end)]


{m: (len(rows := [r async for page in funding_rates(m, end - timedelta(days=1), end) for r in page]), rows[:2]) for m in MARKETS}


# %% [markdown]
# ## `funding_payments`
#
# `account.funding_payments_paged`: one row per hourly accrual. The sign is the venue's opposite of the SDK's: `funding_payment` is positive when paid. Evidence: testnet, a 0.0001 BTC long at a rate of `-0.000750751` (longs receive) has `funding_payment` `-0.004879833131885902`, and the account's USDC balance `1009.970788075131885902` reconciles as `1010 - 0.034091758` (fills' PnL and fees) `+ 0.004879833131885902`; mainnet trader, a long at `+0.0000336` paid `19.47` (row `+19.47`) and a short at `+0.0000054` received (row `-2.44`). So received = `-funding_payment`. Rows not yet settled into the balance (`is_settled` false, while the position stays open) are funding all the same.
#
# Unsettled rows carry `funding_rate_8h: ''` (and `trade_side: ''`), and dividend rows `funding_rate: ''`: typed-risex 0.1.1 declares both rates `Decimal | Literal['']`. Neither rate is mapped: the amount is `funding_payment`, which every row carries. Mainnet trader (with open positions, so unsettled rows) and testnet both validate.

# %%
async def funding_payments(market_id: str | None, /, start: datetime, end: datetime, on: RISEx = testnet, account: str = ME) -> AsyncIterable[Sequence[FundingPayment]]:
  pages = on.account.funding_payments_paged(account, market_id=None if market_id is None else int(market_id), start_time=start, end_time=end, limit=1000)
  async for page in pages:
    yield [FundingPayment(amount=-r['funding_payment'], time=r['block_time']) for r in page]


{
  'testnet': {m: [p async for page in funding_payments(m, end - timedelta(days=2), end) for p in page] for m in MARKETS},
  'mainnet trader': len([p async for page in funding_payments('1', start, end, on=client, account=TRADER) for p in page]),
}


# %% [markdown]
# ## `perp_position`
#
# `account.positions(market_id=...)`: the open position, `size` signed (a short is negative, beside `side: 'SELL'`) and `avg_entry_price`, both 1e18-scaled integers. Not `account.position`: its `avg_entry_price` is `''` while a position is open (testnet, 0.0001 BTC long), and not `portfolio.details`, whose `side` read `0` for a short. No row is flat.

# %%
async def perp_position(market_id: str, /, *, ttl: timedelta | None = None, on: RISEx = client, account: str = TRADER) -> PerpPosition:
  rows = (await on.account.positions(account=account, market_id=int(market_id)))['positions']
  for p in rows:
    if p['market_id'] == int(market_id):
      return PerpPosition(size=Decimal(p['size']) / WAD, entry_price=Decimal(p['avg_entry_price']) / WAD)
  return PerpPosition()


{m: (lambda p: (p.size != 0, p.size > 0))(await perp_position(m)) for m in MARKETS} | {'testnet BTC': await perp_position('1', on=testnet, account=ME)}


# %% [markdown]
# ## `leverage`
#
# `account.position(market_id).leverage`: the account's leverage on the market, which applies to new positions. Where the account never set one it reads the market's maximum: testnet SOL (never set) read `50`, and a 0.1 SOL position's initial margin was exactly 1/50 of its notional. `portfolio.details` reads `0` for those markets instead, so it is not used.

# %%
async def leverage(market_id: str, /, *, ttl: timedelta | None = None, on: RISEx = client, account: str = TRADER) -> Decimal:
  return (await on.account.position(int(market_id), account=account))['position']['leverage']


{'mainnet trader': {m: await leverage(m) for m in MARKETS}, 'testnet': {m: await leverage(m, on=testnet, account=ME) for m in MARKETS}}


# %% [markdown]
# ## `position`
#
# `perp_position`'s size.

# %%
async def position(market_id: str, /, *, ttl: timedelta | None = None) -> Position:
  return Position(size=(await perp_position(market_id)).size)


{m: (await position(m)).size != 0 for m in MARKETS}


# %% [markdown]
# ## `perp_collateral`
#
# `portfolio.details`' `summary`: the cross bucket. Equity is `cross_margin_balance` (USDC balance plus the cross positions' unrealized PnL, matching `account.cross_margin_balance`), free collateral `free_collateral`, margins `total_initial_margin`/`total_maintenance_margin`, leverage `account_leverage` (notional over equity: testnet `6.3866 / 1009.98 = 0.0063`). How the totals treat isolated positions is unobserved (every position seen is cross, `margin_mode 0`), so an account holding an isolated position raises instead of guessing.

# %%
async def perp_collateral(market_id: str | None = None, /, *, ttl: timedelta | None = None, on: RISEx = client, account: str = TRADER) -> PerpCollateral:
  d = await on.portfolio.details(account)
  if any(p['margin_mode'] == 1 and p['size'] != 0 for p in d['positions']):
    raise NotImplementedError('isolated positions')
  s = d['summary']
  return PerpCollateral(
    equity=s['cross_margin_balance'],
    free_collateral=s['free_collateral'],
    initial_margin=s['total_initial_margin'],
    maintenance_margin=s['total_maintenance_margin'],
    leverage=s['account_leverage'],
    margin_mode='cross',
  )


trader = await perp_collateral()
{
  'mainnet trader': {'equity > 0': trader.equity > 0, 'margin > 0': trader.initial_margin > 0},
  'testnet': await perp_collateral(on=testnet, account=ME),
}


# %% [markdown]
# ## `collateral`
#
# `perp_collateral`.

# %%
async def collateral(market_id: str | None = None, /, *, ttl: timedelta | None = None) -> PerpCollateral:
  return await perp_collateral(market_id)


(await collateral()).margin_mode


# %% [markdown]
# ## `collateral_id`
#
# The account's one cross pool, `<account>:perp`: there is no spot exchange, and every order of a cross position draws on `free_collateral`.

# %%
async def collateral_id(market_id: str, /) -> str:
  return 'risex:perp'


{m: await collateral_id(m) for m in MARKETS}


# %% [markdown]
# ## `available_notional`
#
# The SDK default: free collateral times `leverage()`.

# %%
async def available_notional(market_id: str, /, *, ttl: timedelta | None = None, on: RISEx = client, account: str = TRADER) -> Decimal:
  return (await perp_collateral(market_id, on=on, account=account)).free_collateral * await leverage(market_id, on=on, account=account)


{'mainnet trader': {m: await available_notional(m) > 0 for m in MARKETS}, 'testnet': {m: await available_notional(m, on=testnet, account=ME) for m in MARKETS}}

# %% [markdown]
# ## Coverage
#
# Status is one of `verified` (executed live, real data), `empty` (executed live, nothing to show on this account), `blocked` (a typed-client issue, numbered in `typed-client-issues.md`), `not supported` (the venue has no such data) or `not attempted`.
#
# | method | status | note |
# |---|---|---|
# | `markets` | verified | `active` and `unlocked`; mainnet and testnet |
# | `depth` | verified | REST, up to 250 levels per side, no timestamp |
# | `depth_stream` | verified | snapshot then absolute-size updates; one client per market |
# | `tickers` | verified | last and quote volume only: no best bid/ask or base volume published |
# | `rules` | verified | tick, step, minimum; no public fee schedule (`fees=None`) |
# | `fees` | verified | testnet (JWT): tier rates in bps |
# | `candles` | verified | six SDK widths; chunked under the 86,400-interval cap |
# | `query_order` | verified | testnet; unknown id is `None` |
# | `open_orders` | verified | mainnet maker; fill progress from `orders.history` |
# | `trades_history` | verified | testnet fills; mainnet trader |
# | `trades_stream` | verified | testnet subscription here; fills observed in the lifecycle probe and the implementation's testnet run |
# | `place_order` | verified | testnet, through the implementation: post-only rests, IOC fill and no-fill, crossing post-only rejected |
# | `cancel_order` | verified | testnet, through the implementation |
# | `cancel_orders` | verified | SDK default over `cancel_order` |
# | `replace_order` | verified | SDK default (no venue modify), testnet |
# | `replace_orders` | verified | SDK default |
# | `cancel_open_orders` | verified | testnet `cancel_all` |
# | `index` | verified | `index_price`, refreshed |
# | `next_funding` | verified | `expected_funding_rate` stream |
# | `perp_stats` | verified | refreshed markets plus one funding frame |
# | `funding_rates` | verified | hourly settlements |
# | `funding_payments` | verified | testnet and a mainnet trader with open positions (unsettled rows, `funding_rate_8h` `''`), typed-risex 0.1.1 |
# | `perp_position` | verified | mainnet trader; testnet flat |
# | `leverage` | verified | effective leverage (market max when unset) |
# | `position` | verified | |
# | `perp_collateral` | verified | cross bucket; isolated positions raise |
# | `collateral` | verified | |
# | `collateral_id` | verified | `<account>:perp` |
# | `available_notional` | verified | SDK default |

# %% [markdown]
# ## Catalogue
#
# Every ID the verified methods returned, minus what the catalogue translates for this platform. Anything listed is a catalogue addition to make, not something to rename here: the SDK emits venue-native IDs and the catalogue maps them.

# %%
from sdk_dev.catalogue import Ids, gap, load_catalogue

listed_ids = await markets()
ids = Ids(perp_markets=set(listed_ids), assets={USDC})
missing = gap('risex', ids, load_catalogue())
{
  'assets': missing.assets,
  'perp_markets': (len(missing.perp_markets), len(listed_ids)),
  'sample': missing.perp_markets[:10],
}

# %% [markdown]
# ## Cleanup

# %%
await stack.aclose()
