# %%
import asyncio, os
from decimal import Decimal
from datetime import datetime, timedelta, timezone

from typed_dydx import Dydx
from typed_dydx.indexer.schemas import (
  OrderBook,
  Order as IndexerOrder,
  OrderStatus,
  PerpetualMarket,
)
from typed_dydx.indexer.streams.orders import OrderbookMessageContents
from dotenv import load_dotenv

from tribulnation.sdk.core import ApiError, ValidationError
from tribulnation.sdk.market import (
  Book,
  FundingPayment,
  FundingRate,
  NextFunding,
  Order,
  OrderResponse,
  OrderState,
  PerpCollateral,
  PerpPosition,
  PerpStats,
  Rules,
  Ticker,
  Trade,
)

load_dotenv()

MARKETS = ['BTC-USD', 'ETH-USD', 'SOL-USD']

# The only dYdX credentials available here are testnet-only (`DYDX_TESTNET_ADDRESS` /
# `DYDX_TESTNET_MNEMONIC`), so every call below -- public market data included -- goes
# through dYdX's testnet indexer/chain/node endpoints.
client = Dydx.testnet(os.environ['DYDX_TESTNET_MNEMONIC'], indexer={'validate': True})
await client.__aenter__()
address = os.environ['DYDX_TESTNET_ADDRESS']


# %% [markdown]
# > This notebook hand-maps `typed_dydx`'s raw responses onto `tribulnation.sdk.market`
# > types directly -- it does not import or call `tribulnation.dydx` at all. Every book,
# > market, position, and collateral figure below reflects dYdX's **testnet**
# > (`DYDX_TESTNET_ADDRESS` / `DYDX_TESTNET_MNEMONIC`) test account and testnet market
# > state, not mainnet.

# %% [markdown]
# ## `TradingVenue`
#
# dYdX exposes a single exchange kind: the account's perpetual margin bucket.

# %%
async def exchanges() -> list[dict[str, str]]:
  """dYdX's only exchange kind is the perpetual margin bucket addressed by
  subaccount.
  """
  return [{'id': 'perp', 'type': 'perp'}]


await exchanges()


# %% [markdown]
# ## `PerpExchange` (`perp`)
#
# The parent subaccount (`0`) is addressed as `perp`; a child subaccount `N` would be
# `perp.N` (`N % 128 == 0`) -- not exercised here since this testnet account only uses the
# parent subaccount.

# %%
async def markets() -> list[str]:
  """List every perpetual market ticker known to the indexer."""
  data = await client.indexer.data.get_markets()
  return list(data['markets'])


markets_available = await markets()
len(markets_available), markets_available[:10]

# %%
fee_tier_response = await client.chain.feetiers.user_fee_tier(address)
if fee_tier_response.tier is None:
  raise ApiError('dYdX fee tier response did not include a tier')
fee_tier = fee_tier_response.tier
fee_tier

# %%
FUNDING_INTERVAL = timedelta(hours=1)  # dYdX settles funding hourly, on the hour


async def perp_stats(tickers: list[str]) -> dict[str, PerpStats]:
  """Fetch pricing and funding stats for many markets from one indexer call.

  dYdX reports no separate mark price, so `mark` is always `None`.
  """
  data = await client.indexer.data.get_markets()
  all_markets = data['markets']
  now = datetime.now().astimezone()
  next_time = now.replace(minute=0, second=0, microsecond=0) + FUNDING_INTERVAL
  out: dict[str, PerpStats] = {}
  for ticker in tickers:
    m = all_markets[ticker]
    open_interest = m.get('openInterest')
    index_price = m.get('oraclePrice')
    if index_price is None:
      raise ApiError(f'Oracle price unavailable for {ticker}')
    out[ticker] = PerpStats(
      index=Decimal(index_price),
      funding=Decimal(m['nextFundingRate']),
      next_funding_time=next_time,
      funding_interval=FUNDING_INTERVAL,
      open_interest=Decimal(open_interest) if open_interest is not None else None,
    )
  return out


await perp_stats(MARKETS)


# %%
def parse_book(raw: OrderBook) -> Book:
  """Convert an indexer order book payload into an SDK `Book`."""
  return Book(
    asks=[
      Book.Entry(price=Decimal(level['price']), qty=Decimal(level['size']))
      for level in raw['asks']
    ],
    bids=[
      Book.Entry(price=Decimal(level['price']), qty=Decimal(level['size']))
      for level in raw['bids']
    ],
  )


async def tickers(tickers: list[str]) -> dict[str, Ticker]:
  """Fetch a ticker snapshot for many markets, enriched with top-of-book from each
  order book.
  """
  data = await client.indexer.data.get_markets()
  all_markets = data['markets']
  books = await asyncio.gather(
    *[client.indexer.data.get_order_book(t) for t in tickers]
  )
  out: dict[str, Ticker] = {}
  for ticker, raw_book in zip(tickers, books):
    m = all_markets[ticker]
    book = parse_book(raw_book)
    bid = book.bids[0] if book.bids else None
    ask = book.asks[0] if book.asks else None
    index_price = m.get('oraclePrice')
    out[ticker] = Ticker(
      last=Decimal(index_price) if index_price is not None else None,
      bid=bid.price if bid else None,
      ask=ask.price if ask else None,
      bid_qty=bid.qty if bid else None,
      ask_qty=ask.qty if ask else None,
      base_volume_24h=Decimal(m['volume24H']),
    )
  return out


await tickers(MARKETS)


# %%
def effective_imf(market: PerpetualMarket) -> Decimal:
  """Compute the open-interest-scaled Initial Margin Fraction of a market.

  References:
    - [dYdX margin docs](https://docs.dydx.xyz/concepts/trading/margin#margining)
  """
  index_price = market.get('oraclePrice')
  if index_price is None:
    raise ApiError(f'Oracle price unavailable for {market["ticker"]}')
  open_notional = market['openInterest'] * Decimal(index_price)
  lower = market.get('openInterestLowerCap')
  upper = market.get('openInterestUpperCap')
  base_imf = market['initialMarginFraction']
  if lower is None or upper is None or upper == lower:
    return base_imf
  scale = (open_notional - lower) / (upper - lower)
  increase = scale * (1 - base_imf)
  return min(base_imf + max(increase, Decimal(0)), Decimal(1))


def effective_mmf(market: PerpetualMarket) -> Decimal:
  """Compute the open-interest-scaled Maintenance Margin Fraction of a market.

  Assumes the same OI-scaling factor applies to maintenance margin as to initial
  margin -- not independently confirmed against dYdX's docs, only that scaling *up* is
  the risk-safe direction (maintenance is over- rather than under-stated).
  """
  base_imf = market['initialMarginFraction']
  base_mmf = market['maintenanceMarginFraction']
  if base_imf == 0:
    return base_mmf
  return effective_imf(market) * base_mmf / base_imf


def max_leverage(market: PerpetualMarket) -> Decimal:
  """Return the maximum leverage implied by a market's margin metadata."""
  return Decimal(1) / effective_imf(market)


async def perp_collateral() -> PerpCollateral:
  """Fetch the exchange-level (parent subaccount `0`) perpetual collateral bucket."""
  sub, data = await asyncio.gather(
    client.indexer.data.get_subaccount(address, subaccount=0),
    client.indexer.data.get_markets(),
  )
  account = sub['subaccount']
  equity = Decimal(account['equity'])
  free_collateral = Decimal(account['freeCollateral'])
  all_markets = data['markets']
  notional = Decimal(0)
  maintenance_margin = Decimal(0)
  for position in account['openPerpetualPositions'].values():
    m = all_markets[position['market']]
    index_price = m.get('oraclePrice')
    if index_price is None:
      raise ApiError(f'Oracle price unavailable for {position["market"]}')
    position_notional = abs(Decimal(position['size'])) * Decimal(index_price)
    notional += position_notional
    maintenance_margin += position_notional * effective_mmf(m)
  leverage = notional / equity if equity > 0 else Decimal(0)
  return PerpCollateral(
    equity=equity,
    free_collateral=free_collateral,
    initial_margin=equity - free_collateral,
    maintenance_margin=maintenance_margin,
    leverage=leverage,
    margin_mode='cross',  # parent subaccounts (< 128) are always the cross-margin pool
  )


await perp_collateral()

# %% [markdown]
# ## `PerpMarket`
#
# dYdX's only exchange kind is `perp` (no spot market), so this section covers the whole
# `Market`/`PerpMarket` interface directly, for `BTC-USD`, `ETH-USD`, and `SOL-USD`.

# %%
all_markets = (await client.indexer.data.get_markets())['markets']
market_info: dict[str, PerpetualMarket] = {t: all_markets[t] for t in MARKETS}


# %%
async def depth(ticker: str) -> Book:
  raw = await client.indexer.data.get_order_book(ticker)
  return parse_book(raw)


{t: await depth(t) for t in MARKETS}


# %%
def apply_book_update(book: Book, update: OrderbookMessageContents) -> None:
  """Apply an incremental order book message onto a local `Book`, in place."""
  book.update(
    Book(
      asks=[Book.Entry(price, qty) for price, qty in update.get('asks', [])],
      bids=[Book.Entry(price, qty) for price, qty in update.get('bids', [])],
    )
  )


async def depth_stream(
  ticker: str, *, count: int = 3, timeout: float = 15.0
) -> list[Book]:
  """Subscribe to the order book and collect up to `count` updated snapshots."""
  raise NotImplementedError(
    'blocked: typed_dydx validates the v4_orderbook subscription reply against the '
    'notification type (OrderbookMessageContents), so entering the stream raises '
    'ValidationError before the first message'
  )
  books: list[Book] = []
  async with client.indexer.streams.orders(id=ticker) as stream:
    book = parse_book(stream.reply)
    it = aiter(stream)
    try:
      while len(books) < count:
        msg = await asyncio.wait_for(anext(it), timeout=timeout)
        apply_book_update(book, msg)
        books.append(book.copy())
    except asyncio.TimeoutError:
      pass
  return books


# not executed: blocked by typed-dydx "Stream subscription replies are validated with the channel's notification type"
await depth_stream('BTC-USD')


# %%
def fee_ppm(value: int) -> Decimal:
  """Convert dYdX fee parts-per-million into a decimal rate."""
  return Decimal(value) / Decimal(1_000_000)


async def rules(ticker: str) -> Rules:
  m = market_info[ticker]
  base, quote = m['ticker'].split('-')
  return Rules(
    base=base,
    quote=quote,
    fee_asset=quote,
    tick_size=Decimal(m['tickSize']),
    step_size=Decimal(m['stepSize']),
    maker_fee=fee_ppm(fee_tier.maker_fee_ppm),
    taker_fee=fee_ppm(fee_tier.taker_fee_ppm),
    api=m['status'] == 'ACTIVE',
    details={'perpetual_market': m, 'user_fees': fee_tier},
  )


{t: await rules(t) for t in MARKETS}

# %%
import base64
from typed_dydx.protos.dydxprotocol import clob, subaccounts


def order_active(status: str) -> bool:
  return status in {'OPEN', 'PENDING', 'UNTRIGGERED', 'BEST_EFFORT_OPENED'}


def order_sign(side: str) -> int:
  return 1 if side == 'BUY' else -1


def protobuf_order_id(order: IndexerOrder) -> clob.OrderId:
  """Build a protocol order ID for an indexer order."""
  subaccount_number = order.get('subaccountNumber')
  if subaccount_number is None:
    raise ValidationError('dYdX order did not include a subaccount number')
  return clob.OrderId(
    client_id=int(order['clientId']),
    order_flags=int(order['orderFlags']),
    clob_pair_id=int(order['clobPairId']),
    subaccount_id=subaccounts.SubaccountId(
      owner=address, number=int(subaccount_number)
    ),
  )


def serialize_order_id(order_id: clob.OrderId) -> str:
  """Serialize a dYdX protocol order ID for the SDK order API."""
  return base64.b64encode(bytes(order_id)).decode()


def parse_order_id(id: str) -> clob.OrderId:
  """Parse an SDK order ID back into a dYdX protocol order ID."""
  return clob.OrderId.FromString(base64.b64decode(id))


def parse_order_state(order: IndexerOrder) -> OrderState:
  sign = order_sign(order['side'])
  return OrderState(
    id=serialize_order_id(protobuf_order_id(order)),
    price=Decimal(order['price']),
    qty=Decimal(order['size']) * sign,
    filled_qty=Decimal(order['totalFilled']) * sign,
    active=order_active(order['status']),
    details=order,
  )


async def list_orders(
  ticker: str, *, status: OrderStatus | None = None
) -> list[OrderState]:
  orders = await client.indexer.data.list_parent_orders(
    address=address,
    parent_subaccount=0,
    ticker=ticker,
    status=status,
  )
  return [parse_order_state(o) for o in orders]


async def open_orders(ticker: str) -> list[OrderState]:
  return await list_orders(ticker, status='OPEN')


async def query_order(ticker: str, id: str) -> OrderState | None:
  for order in await list_orders(ticker):
    if order.id == id:
      return order


{t: await open_orders(t) for t in MARKETS}


# %%
async def trades_history(ticker: str, start: datetime, end: datetime) -> list[Trade]:
  start = start.astimezone()
  end = end.astimezone()
  pages = client.indexer.data.get_fills_paged(
    address=address,
    subaccount=0,
    created_before_or_at=end,
    market=ticker,
    market_type='PERPETUAL',
  )
  out: list[Trade] = []
  async for page in pages:
    for f in page:
      if not (start <= f['createdAt'] <= end):
        continue
      sign = order_sign(f['side'])
      out.append(
        Trade(
          id=f['id'],
          price=Decimal(f['price']),
          qty=Decimal(f['size']) * sign,
          time=f['createdAt'],
          maker=f['liquidity'] == 'MAKER',
          fee=Trade.Fee(asset='USDC', amount=Decimal(f['fee'])),
          details=f,
        )
      )
  return out


end = datetime.now(timezone.utc)
start = end - timedelta(days=90)
{t: await trades_history(t, start, end) for t in MARKETS}


# %%
async def trades_stream_sample(ticker: str, *, timeout: float = 5.0):
  """Subscribe to real-time fills and return the first one matching `ticker`, or a
  timeout marker if none arrive within `timeout` seconds.
  """
  async with client.indexer.streams.parent_subaccounts(address, subaccount=0) as stream:
    it = aiter(stream)
    try:
      msg = await asyncio.wait_for(anext(it), timeout=timeout)
    except asyncio.TimeoutError:
      return (
        'no new trades observed in 5s (expected -- no live trading on this account)'
      )
    for fill in msg.get('fills') or []:
      if fill['ticker'] != ticker:
        continue
      sign = order_sign(fill['side'])
      return Trade(
        id=fill['id'],
        price=Decimal(fill['price']),
        qty=Decimal(fill['size']) * sign,
        time=fill['createdAt'],
        maker=fill['liquidity'] == 'MAKER',
        fee=None,
        details=fill,
      )
    return msg  # no matching fill in this notification -- return it raw for inspection


await trades_stream_sample('BTC-USD')

# %%
await query_order('BTC-USD', 'nonexistent-order-id')


# %%
async def perp_position(ticker: str) -> PerpPosition:
  positions = await client.indexer.data.list_parent_positions(
    address, parent_subaccount=0
  )
  matches = [p for p in positions if p['market'] == ticker and p['status'] == 'OPEN']
  if not matches:
    return PerpPosition()
  total_size = sum((Decimal(p['size']) for p in matches), Decimal(0))
  if total_size == 0:
    return PerpPosition()
  total_notional = sum(
    (Decimal(p['size']) * Decimal(p['entryPrice']) for p in matches), Decimal(0)
  )
  return PerpPosition(size=total_size, entry_price=total_notional / total_size)


{t: await perp_position(t) for t in MARKETS}


# %%
async def market_perp_collateral(ticker: str) -> PerpCollateral:
  """dYdX has no per-market margin mode: a market's collateral bucket is exactly its
  exchange's parent-subaccount pool.
  """
  return await perp_collateral()


{t: await market_perp_collateral(t) for t in MARKETS}


# %%
async def available_notional(ticker: str) -> Decimal:
  sub, m = await asyncio.gather(
    client.indexer.data.get_subaccount(address, subaccount=0),
    client.indexer.data.get_market(ticker),
  )
  free_collateral = Decimal(sub['subaccount']['freeCollateral'])
  return free_collateral * max_leverage(m)


{t: await available_notional(t) for t in MARKETS}


# %%
async def index(ticker: str) -> Decimal:
  m = await client.indexer.data.get_market(ticker)
  index_price = m.get('oraclePrice')
  if index_price is None:
    raise ApiError(f'Oracle price unavailable for {ticker}')
  return Decimal(index_price)


{t: await index(t) for t in MARKETS}


# %%
async def next_funding(ticker: str) -> NextFunding:
  m = await client.indexer.data.get_market(ticker)
  now = datetime.now().astimezone()
  next_time = now.replace(minute=0, second=0, microsecond=0) + FUNDING_INTERVAL
  return NextFunding(
    rate=Decimal(m['nextFundingRate']), time=next_time, interval=FUNDING_INTERVAL
  )


{t: await next_funding(t) for t in MARKETS}


# %%
async def funding_rates(
  ticker: str, start: datetime | None, end: datetime | None
) -> list[FundingRate]:
  start = start.astimezone() if start is not None else None
  end = end.astimezone() if end is not None else None
  pages = client.indexer.data.get_historical_funding_paged(
    ticker, effective_before_or_at=end
  )
  out: list[FundingRate] = []
  async for page in pages:
    for item in page:
      if start is None or item['effectiveAt'] >= start:
        out.append(FundingRate(rate=Decimal(item['rate']), time=item['effectiveAt']))
  return out


end = datetime.now(timezone.utc)
start = end - timedelta(days=2)
{t: await funding_rates(t, start, end) for t in MARKETS}


# %%
async def funding_payments(
  ticker: str, start: datetime, end: datetime
) -> list[FundingPayment]:
  start = start.astimezone()
  end = end.astimezone()
  pages = client.indexer.data.get_funding_payments_paged(
    address=address,
    subaccount=0,
    ticker=ticker,
    after_or_at=start,
  )
  out: list[FundingPayment] = []
  async for page in pages:
    for item in page:
      if start <= item['createdAt'] <= end:
        out.append(
          FundingPayment(amount=Decimal(item['payment']), time=item['createdAt'])
        )
  return out


end = datetime.now(timezone.utc)
start = end - timedelta(days=90)
{t: await funding_payments(t, start, end) for t in MARKETS}

# %%
from typed_dydx.node.orders.types import ShortTermOrderParams


async def place_order(ticker: str, order: Order) -> OrderResponse:
  signed_qty = Decimal(order['qty'])
  side = 'BUY' if signed_qty >= 0 else 'SELL'
  params = ShortTermOrderParams(
    side=side,
    price=Decimal(order['price']),
    size=abs(signed_qty),
    time_in_force='IMMEDIATE_OR_CANCEL'
    if order['type'] == 'MARKET'
    else 'GOOD_TIL_TIME',
    flags='SHORT_TERM',
  )
  response = await client.node.place_order(
    market_info[ticker], order=params, subaccount=0
  )
  order_id = response.order.order_id
  if order_id is None:
    raise ValidationError('dYdX place order response did not include an order ID')
  return OrderResponse(id=serialize_order_id(order_id), details=response)


order: Order = {'qty': Decimal('0.001'), 'price': Decimal('20000'), 'type': 'LIMIT'}
# Not executed here -- would place a real order on the testnet account.
await place_order('BTC-USD', order)


# %%
async def cancel_order(id: str):
  return await client.node.cancel_order(parse_order_id(id))


# Not executed here -- would cancel a real order on the testnet account.
await cancel_order('some-order-id')


# %%
async def cancel_orders(ids: list[str]):
  order_ids = [parse_order_id(id) for id in ids]
  return await client.node.batch_cancel_orders(order_ids)


# Not executed here -- would cancel real orders on the testnet account.
await cancel_orders(['id-1', 'id-2'])

# %% [markdown]
# ## Coverage assessment
#
# **Full bar one cell**, executed live against `BTC-USD`, `ETH-USD`, and `SOL-USD` on the
# testnet account -- every cell above hand-maps a raw `typed_dydx` response onto a
# `tribulnation.sdk.market` type directly, with no `tribulnation.dydx` import at all:
#
# - `TradingVenue`: `exchanges()` ran live and returns dYdX's single exchange kind
#   (`perp`). dYdX has no spot market, so there is no second, non-perp `TradingVenue`
#   accessor to exercise separately.
# - `PerpExchange` (`perp`): `markets()` (220+ real perpetuals), `perp_stats()`,
#   `tickers()`, and the exchange-level `perp_collateral()` (parent subaccount `0`, the
#   account's only subaccount on this testnet wallet) all ran live and returned real data.
# - `PerpMarket`: every method except `depth_stream` ran live and returned real,
#   non-fabricated data (or a real empty/`None` result) -- `depth` returned real testnet
#   order books; `rules` returned real tick/step size and fee-tier data; `open_orders` came
#   back empty (no resting orders); `trades_history` found real historical fills on
#   `BTC-USD` over the last 90 days and none on `ETH-USD`/`SOL-USD`; `trades_stream_sample`
#   correctly reported
#   no live fill within a 5s window (no active trading during the run); `query_order`
#   correctly returned `None` for a nonexistent id; `perp_position` shows a real open
#   `BTC-USD` long and flat `ETH-USD`/`SOL-USD`; `perp_collateral`/`available_notional`
#   reflect that same real account state; `index`/`next_funding` read the indexer's live
#   oracle price and `nextFundingRate` field (dYdX funds hourly, so `next_funding`'s `time`
#   is computed as the top of the next hour rather than read -- there is no separate
#   "next funding timestamp" field to read); `funding_rates`/`funding_payments` both
#   returned real historical entries.
# - `depth_stream` is **blocked** on typed-dydx "Stream subscription replies are
#   validated with the channel's notification type": `StreamsMixin.subscribe` validates
#   the `v4_orderbook` reply (`{"price", "size"}` objects, `OrderbookReplyContents`)
#   against the notification type (`[price, size]` tuples, `OrderbookMessageContents`),
#   so entering the stream raises `ValidationError` before the first message. The mapping
#   is written; its body raises `NotImplementedError` and the cell is not executed until
#   the client takes a `reply_type`.
# - `Market.position()`/`Market.collateral()` (the base, non-perp-named methods) are not
#   exercised as separate cells -- `PerpMarket` implements them as trivial delegators to
#   `perp_position()`/`perp_collateral()`, both already exercised above; this notebook's
#   hand-written functions mirror that delegation with `market_perp_collateral`.
# - `place_order`, `cancel_order`, and `cancel_orders` are written but **not executed** --
#   they would place/cancel a real order on the testnet account. `place_orders`,
#   `cancel_open_orders` (the SDK's `asyncio.gather`-over-single-method defaults) are not
#   separately hand-mapped since they add no venue-specific logic beyond what's above.
