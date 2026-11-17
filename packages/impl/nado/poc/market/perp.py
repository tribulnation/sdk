# %% [markdown]
# # nado `market` PoC: perpetuals
#
# Maps `typed_nado` onto the SDK `market` surface's perpetual exchange, one method per cell, each executed live on mainnet. The rules, and how a typed-client issue is reported in `typed-client-issues.md`, are in `.agents/skills/sdk-poc/SKILL.md`.
#
# Nado has no API keys: reads are public, so the client is public and account reads name the subaccount (`NADO_ADDRESS`'s `default`). Every value is an x18 integer.

# %%
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from typing_extensions import Any

from dotenv import load_dotenv
from typed_nado import Nado
from typed_nado.core.auth import subaccount_bytes32

from tribulnation.sdk.market import (
  Book,
  Candle,
  Fees,
  FundingPayment,
  FundingRate,
  NextFunding,
  OrderState,
  PerpCollateral,
  PerpPosition,
  PerpStats,
  Rules,
  Ticker,
  Trade,
)

load_dotenv()

client = Nado.new(public=True)
SENDER = subaccount_bytes32(os.environ['NADO_ADDRESS'], 'default')
X18 = Decimal(10) ** 18


def x18(v: int) -> Decimal:
  """An x18 integer as a decimal."""
  return Decimal(int(v)) / X18


MARKETS = ['BTC-PERP', 'ETH-PERP']

end = datetime.now(timezone.utc)
start = end - timedelta(days=7)

# %% [markdown]
# ## Surface
#
# What the client exposes. Widen or narrow the filter until every endpoint the mapping below uses is listed here.

# %%
from sdk_dev.surface import surface

print(
  surface(
    'typed_nado',
    'Nado',
    grep=r'symbols|liquidity|book_depth|tickers|market_prices|perp_prices|funding|all_products|candlesticks|subaccount|order|matches|fill|fee_rates|isolated|positions|price',
  )
)

# %% [markdown]
# ## `markets`
#
# Every perpetual's symbol (untradable ones included).

# %%
symbols = (await client.gateway.symbols())['symbols']
PRODUCT = {name: s['product_id'] for name, s in symbols.items()}


async def markets() -> list[str]:
  """Perpetual symbols."""
  return [name for name, s in symbols.items() if s['type'] == 'perp']


len(await markets()), (await markets())[:5]

# %% [markdown]
# ## `depth`
#
# `market_liquidity`: at most 100 levels per side.


# %%
async def depth(market_id: str, levels: int = 5) -> Book:
  """The aggregated book."""
  raw = await client.gateway.market_liquidity(
    product_id=PRODUCT[market_id], depth=levels
  )
  return Book(
    bids=[Book.Entry(x18(p), x18(q)) for p, q in raw['bids']],
    asks=[Book.Entry(x18(p), x18(q)) for p, q in raw['asks']],
    time=raw['timestamp'],
  )


{m: (await depth(m)).best_bid for m in MARKETS}

# %% [markdown]
# ## `depth_stream`
#
# `book_depth` diffs (absolute sizes, `0` deletes) applied to a snapshot: diffs with `max_timestamp` not past the snapshot's `timestamp` are already in it; each diff's `last_max_timestamp` is the previous one's `max_timestamp`.


# %%
async def depth_stream(market_id: str, updates: int = 5) -> Book:
  """The book after `updates` diffs."""
  stream = await client.streams.book_depth(PRODUCT[market_id])
  snap = await client.gateway.market_liquidity(product_id=PRODUCT[market_id], depth=100)
  book = Book(
    bids=[Book.Entry(x18(p), x18(q)) for p, q in snap['bids']],
    asks=[Book.Entry(x18(p), x18(q)) for p, q in snap['asks']],
    time=snap['timestamp'],
  )
  n = 0
  async for diff in stream:
    if diff['max_timestamp'] <= snap['timestamp']:
      continue
    book.update(
      Book(
        bids=[Book.Entry(x18(p), x18(q)) for p, q in diff['bids']],
        asks=[Book.Entry(x18(p), x18(q)) for p, q in diff['asks']],
        time=diff['max_timestamp'],
      )
    )
    n += 1
    if n == updates:
      break
  await stream.unsubscribe()
  return book.limit(3)


await depth_stream('BTC-PERP')

# %% [markdown]
# ## `tickers`
#
# Last price and 24h volumes from the archive's `tickers` (floats, issue `Ticker.last_price`), best bid/ask from `market_prices`.


# %%
async def tickers(names: list[str]) -> dict[str, Ticker]:
  """Two requests for every market."""
  rows = await client.archive_v2.tickers('perp')
  prices = await client.gateway.market_prices([PRODUCT[n] for n in names])
  by_id = {t['product_id']: t for t in rows.values()}
  best = {p['product_id']: p for p in prices['market_prices']}
  out: dict[str, Ticker] = {}
  for n in names:
    t, p = by_id[PRODUCT[n]], best[PRODUCT[n]]
    out[n] = Ticker(
      last=Decimal(repr(t['last_price'])),
      bid=x18(p['bid_x18']),
      ask=x18(p['ask_x18']),
      base_volume_24h=Decimal(repr(t['base_volume'])),
      quote_volume_24h=Decimal(repr(t['quote_volume'])),
    )
  return out


await tickers(MARKETS)

# %% [markdown]
# ## `rules`
#
# `symbols`: tick, size step, minimum notional (`min_size` is in USDT0) and the default rates.


# %%
async def rules(market_id: str) -> Rules:
  """The product's trading configuration."""
  s = symbols[market_id]
  return Rules(
    fee_asset='USDT0',
    tick_size=x18(s['price_increment_x18']),
    step_size=x18(s['size_increment']),
    min_value=x18(s['min_size']),
    fees=Fees.symmetric(
      maker=x18(s['maker_fee_rate_x18']), taker=x18(s['taker_fee_rate_x18'])
    ),
    api=s['trading_status'] == 'live',
  )


{m: await rules(m) for m in MARKETS}

# %% [markdown]
# ## `fees`
#
# `fee_rates` of the subaccount, indexed by product id.


# %%
async def fees(market_id: str) -> Fees:
  """The subaccount's rates on one product."""
  r = await client.gateway.fee_rates(SENDER)
  pid = PRODUCT[market_id]
  return Fees.symmetric(
    maker=x18(r['maker_fee_rates_x18'][pid]), taker=x18(r['taker_fee_rates_x18'][pid])
  )


{m: await fees(m) for m in MARKETS}

# %% [markdown]
# ## `candles`
#
# `candlesticks`, newest first from `max_time`; base volume only.


# %%
async def candles(market_id: str) -> list[Candle]:
  """The last 3 hourly candles."""
  raw = await client.archive.candlesticks(
    product_id=PRODUCT[market_id], granularity=3600, max_time=end, limit=3
  )
  return [
    Candle(
      time=c['timestamp'],
      open=x18(c['open_x18']),
      high=x18(c['high_x18']),
      low=x18(c['low_x18']),
      close=x18(c['close_x18']),
      volume=x18(c['volume']),
    )
    for c in raw['candlesticks']
  ]


await candles('BTC-PERP')

# %% [markdown]
# ## `query_order` and `open_orders`
#
# `subaccount_orders`/`order` for resting orders (by digest), the archive's `orders` for ones that filled. The account rests nothing now; the lifecycle was verified through the implementation (see Coverage).


# %%
async def open_orders(market_id: str) -> list[OrderState]:
  """Resting orders."""
  r = await client.gateway.subaccount_orders(SENDER, product_id=PRODUCT[market_id])
  return [
    OrderState(
      id=o['digest'],
      price=x18(o['price_x18']),
      qty=x18(o['amount']),
      filled_qty=x18(o['amount']) - x18(o['unfilled_amount']),
      active=True,
    )
    for o in r['orders']
  ]


{m: await open_orders(m) for m in MARKETS}

# %% [markdown]
# ## `trades_history`
#
# `matches` with their `txs` (the time); the price is `-(quote_filled + fee) / base_filled`.


# %%
async def trades_history(market_id: str) -> list[Trade]:
  """Personal fills of the last week."""
  r = await client.archive.matches(
    [SENDER], product_ids=[PRODUCT[market_id]], max_time=end, limit=100
  )
  times = {int(t['submission_idx']): t['timestamp'] for t in r['txs']}
  return [
    Trade(
      id=f'{m["submission_idx"]}:{m["digest"]}',
      order_id=m['digest'],
      price=-(x18(m['quote_filled']) + x18(m['fee'])) / x18(m['base_filled']),
      qty=x18(m['base_filled']),
      time=times[int(m['submission_idx'])],
      maker=not m['is_taker'],
      fee=Trade.Fee(amount=x18(m['fee']), asset='USDT0'),
    )
    for m in r['matches']
  ]


{m: await trades_history(m) for m in MARKETS}

# %% [markdown]
# ## `trades_stream`
#
# The public `fill` stream of the subaccount.

# %%
# not executed: waits for a fill, and this account places none in a PoC
stream = await client.streams.fill(SENDER, product_id=PRODUCT['BTC-PERP'])
async for fill in stream:
  print(fill)
  break

# %% [markdown]
# ## `perp_position`, `perp_collateral`, `leverage`, `available_notional`, `collateral_id`
#
# `subaccount_info`: healths `[initial, maintenance, unweighted]`, balances and positions; leverage from the initial risk weights (`all_products`), cross-checked against the venue's `max_order_size`.


# %%
async def account(market_id: str) -> dict[str, Any]:
  """Every margin read of one market."""
  info = await client.gateway.subaccount_info(subaccount=SENDER)
  pid = PRODUCT[market_id]
  h = [x18(x['health']) for x in info['healths']]
  size = next(
    (
      x18(b['balance']['amount'])
      for b in info['perp_balances']
      if b['product_id'] == pid
    ),
    Decimal(0),
  )
  products = await client.gateway.all_products()
  risk = next(p['risk'] for p in products['perp_products'] if p['product_id'] == pid)
  margin = max(
    1 - x18(risk['long_weight_initial_x18']), x18(risk['short_weight_initial_x18']) - 1
  )
  price = 60000 * 10**18 if market_id == 'BTC-PERP' else 2000 * 10**18
  max_size = await client.gateway.max_order_size(
    SENDER, product_id=pid, price_x18=price, direction='long'
  )
  return {
    'position': PerpPosition(size=size),
    'collateral': PerpCollateral(
      equity=h[2],
      free_collateral=max(h[0], Decimal(0)),
      initial_margin=h[2] - h[0],
      maintenance_margin=h[2] - h[1],
      leverage=Decimal(0),
      margin_mode='cross',
    ),
    'leverage': 1 / margin,
    'available_notional': max(h[0], Decimal(0)) / margin,
    'venue_max_notional': x18(max_size['max_order_size']) * x18(price),
    'collateral_id': 'nado:spot:USDT0',
  }


{m: await account(m) for m in MARKETS}

# %% [markdown]
# ## `index`, `next_funding`, `perp_stats`
#
# `perp_prices` (index, mark), `funding_rates` (a 24-hour rate: over 24 per hourly settlement), `all_products` (open interest).


# %%
async def perp_stats(names: list[str]) -> dict[str, PerpStats]:
  """Three requests for every market."""
  ids = [PRODUCT[n] for n in names]
  prices = await client.archive.perp_prices(ids)
  rates = await client.archive.funding_rates(ids)
  products = await client.gateway.all_products()
  oi = {
    p['product_id']: x18(p['state']['open_interest']) for p in products['perp_products']
  }
  return {
    n: PerpStats(
      index=x18(prices[str(PRODUCT[n])]['index_price_x18']),
      mark=x18(prices[str(PRODUCT[n])]['mark_price_x18']),
      funding=x18(rates[str(PRODUCT[n])]['funding_rate_x18']) / 24,
      funding_interval=timedelta(hours=1),
      open_interest=oi[PRODUCT[n]],
    )
    for n in names
  }


async def next_funding(market_id: str) -> NextFunding:
  """The predicted rate of the next hourly settlement."""
  r = await client.archive.funding_rate(PRODUCT[market_id])
  return NextFunding(
    rate=x18(r['funding_rate_x18']) / 24,
    time=r['update_time'].replace(minute=0, second=0, microsecond=0)
    + timedelta(hours=1),
    interval=timedelta(hours=1),
  )


async def index(market_id: str) -> Decimal:
  """The index price."""
  return x18((await client.archive.price(PRODUCT[market_id]))['index_price_x18'])


await perp_stats(MARKETS), await next_funding('BTC-PERP'), await index('BTC-PERP')

# %% [markdown]
# ## `funding_rates` and `funding_payments`
#
# `funding_rate_history` (realized hourly rates, oldest first); `interest_and_funding` (received-positive amounts).


# %%
async def funding_rates(market_id: str) -> list[FundingRate]:
  """The last six hourly rates."""
  r = await client.archive.funding_rate_history(
    product_id=PRODUCT[market_id], start_time=end - timedelta(hours=6), end_time=end
  )
  return [
    FundingRate(rate=x18(x['funding_rate_x18']), time=x['timestamp'])
    for x in r['funding_rates']
  ]


async def funding_payments(market_id: str) -> list[FundingPayment]:
  """Personal payments, newest first."""
  r = await client.archive.interest_and_funding(
    SENDER, product_ids=[PRODUCT[market_id]], limit=100
  )
  return [
    FundingPayment(amount=x18(p['amount']), time=p['timestamp'])
    for p in r['funding_payments']
    if start <= p['timestamp']
  ]


await funding_rates('BTC-PERP'), await funding_payments('BTC-PERP')

# %% [markdown]
# ## Orders
#
# `place_order` (EIP-712 `Order`, appendix by type: `LIMIT` 1, `POST_ONLY` 1537, `MARKET` an IOC limit), `place_orders`, `cancel_orders`, `cancel_and_place`, `cancel_product_orders`. Order-placing cells are never run in a PoC; the lifecycle was run through the implementation on mainnet (see Coverage).

# %%
# not executed: changes the account
signer = Nado.new()
await signer.gateway.place_order(
  product_id=PRODUCT['BTC-PERP'],
  order={
    'priceX18': 32000 * 10**18,
    'amount': 3_150_000_000_000_000,
    'expiration': datetime(2100, 1, 1, tzinfo=timezone.utc),
    'appendix': 1537,
  },
)

# %% [markdown]
# ## Coverage
#
# Status is one of `verified` (executed live, real data), `empty` (executed live, nothing to show on this account), `blocked` (a typed-client issue in `typed-client-issues.md`), `not supported` (the venue has no such data) or `not attempted`.
#
# | method | status | note |
# |---|---|---|
# | `markets` | verified | 83 perpetuals, untradable ones included |
# | `depth` | verified | at most 100 levels per side |
# | `depth_stream` | verified | diffs applied to a snapshot reproduced a later snapshot's top 10 levels exactly (2026-11-17) |
# | `tickers` | verified | last price and volumes are floats on the wire: `Ticker.last_price` issue |
# | `rules` | verified | |
# | `fees` | verified | |
# | `candles` | verified | no quote volume or trade count |
# | `query_order` | verified | resting order through the implementation; the archive path is empty (no fill yet) |
# | `open_orders` | verified | through the implementation, with a resting post-only order |
# | `trades_history` | empty | the account has never filled; the price formula checked against recorded BTC-PERP fills |
# | `trades_stream` | empty | subscribed through the implementation; no fill |
# | `perp_position` | empty | flat account; entry price from the archive's open position window |
# | `perp_collateral` | verified | |
# | `leverage` | verified | BTC-PERP 50x; `available_notional` equals the venue's `max_order_size` notional for a buy below the oracle (above it, the venue also charges the immediate loss) |
# | `available_notional` | verified | |
# | `collateral_id` | verified | unified account: USDT0's spot id |
# | `index` | verified | |
# | `next_funding` | verified | |
# | `perp_stats` | verified | |
# | `funding_rates` | verified | |
# | `funding_payments` | empty | no position has ever been held |
# | `place_order` | verified | POST_ONLY and LIMIT rested and were cancelled (mainnet, through the implementation); MARKET's refusal path (`2056`); a fill not attempted: needs Alex's OK for a taker round trip |
# | `place_orders` | verified | a valid batch rested; a batch with one invalid order was refused whole |
# | `cancel_order` | verified | a second cancel raises `OrderNotFound` |
# | `cancel_orders` | verified | |
# | `replace_order` | verified | atomic `cancel_and_place`; a refused replacement left the original resting |
# | `replace_orders` | verified | the SDK default over `replace_order` |
# | `cancel_open_orders` | verified | |

# %% [markdown]
# ## Catalogue
#
# Every ID the verified methods returned, minus what the catalogue translates for this platform. Anything listed is a catalogue addition to make, not something to rename here: the SDK emits venue-native IDs and the catalogue maps them.

# %%
from sdk_dev.catalogue import Ids, gap, load_catalogue

listed = await markets()
ids = Ids(perp_markets={f'perp:{m}' for m in listed}, assets={'USDT0'})
gap('nado', ids, load_catalogue())
