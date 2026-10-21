# %% [markdown]
# # margin-trade `market` PoC: spot
#
# Maps `typed_margin_trade` onto the SDK `market` surface for the spot exchange, one method per cell, each executed live. The rules, and how a typed-client issue is reported in `typed-client-issues.md`, are in `.agents/skills/sdk-poc/SKILL.md`.
#
# Signed calls run against **testnet** with the approved agent key (`MARGIN_TRADE_TESTNET_AGENT_PRIVATE_KEY`, master address as `vault`, from the repo-root `.env`), under the `typed_margin_trade` `client.toml` policy. The testnet spot book is empty and the account holds no spot balance, so reads that need real rows (book, fills, fill stream) also run through a credential-free **mainnet** client against public data: the order book, and the fills of `SPOT_TRADER`, a mainnet address that trades `PRL/USDC`. No signed call goes to mainnet. The lifecycle cell moves 20 test USDC from the perp to the spot wallet, rests and cancels post-only buys, and moves it back.

# %%
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing_extensions import Any, AsyncIterator, AsyncIterable, Collection, Literal, Mapping, Sequence

from dotenv import dotenv_values
from sdk_dev.repo import repo_root
from typed_margin_trade import MarginTrade
from typed_margin_trade.schemas import Fill, L2Book, OrderSpec

from tribulnation.sdk.market import Book, Candle, CandleInterval, Collateral, Fees, Order, OrderResponse, OrderState, Position, Rules, Settings, Ticker, Trade
from tribulnation.sdk.market.exchange import OverflowPolicy

env = dotenv_values(repo_root() / '.env')
ADDRESS = env['MARGIN_TRADE_TESTNET_ADDRESS'] or ''
client = await MarginTrade.new(env['MARGIN_TRADE_TESTNET_AGENT_PRIVATE_KEY'], vault=ADDRESS, mainnet=False).__aenter__()
public = await MarginTrade.new(public=True).__aenter__()
master = await MarginTrade.new(env['MARGIN_TRADE_TESTNET_PRIVATE_KEY'], mainnet=False).__aenter__()
"""Only for the lifecycle's perp/spot transfers: an agent's `usdClassTransfer` debits the agent's own (empty) account."""

SPOT_TRADER = 'HZEB64qX94oiDsKNisSxYSWuEaKdfsD4Rn1ZEToAw68a'  # mainnet account with PRL/USDC fills
MARKETS = ['PRL/USDC']
SPOT_ASSET_OFFSET = 10000
"""Spot order actions address pair `i` as asset `10000 + i` (`marketMetadata` lists PRL/USDC at index 10000)."""
MAX_SIG_FIGS = 5
SPOT_MAX_DECIMALS = 8

end = datetime.now(timezone.utc)
start = end - timedelta(days=7)


def round_price(price: Decimal, sz_decimals: int) -> Decimal:
  """At most five significant figures and `8 - szDecimals` decimals; integers always pass."""
  if price == price.to_integral_value():
    return Decimal(f'{price.to_integral_value():f}')
  places = min(MAX_SIG_FIGS - 1 - price.adjusted(), SPOT_MAX_DECIMALS - sz_decimals)
  rounded = price.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
  return Decimal(f'{rounded.normalize():f}')


async def pairs(via: MarginTrade = client) -> dict[str, tuple[Any, Any, Any]]:
  """Each pair by name with its base and quote tokens."""
  meta = await via.info.spot_meta()
  tokens = {t['index']: t for t in meta['tokens']}
  return {p['name']: (p, tokens[p['tokens'][0]], tokens[p['tokens'][1]]) for p in meta['universe']}


def parse_book(raw: L2Book, levels: int | None = None) -> Book:
  sides = raw['levels']
  bids, asks = (sides[0], sides[1]) if sides else ([], [])
  book = Book(
    bids=[Book.Entry(price=level['px'], qty=level['sz']) for level in bids],
    asks=[Book.Entry(price=level['px'], qty=level['sz']) for level in asks],
    time=raw['time'],
  )
  return book.limit(levels) if levels else book


def parse_trade(fill: Fill) -> Trade:
  sign = 1 if fill['side'] == 'B' else -1
  return Trade(
    id=str(fill['tid']),
    order_id=str(fill['oid']),
    price=fill['px'],
    qty=sign * fill['sz'],
    time=fill['time'],
    maker=not fill['isTaker'],
    fee=Trade.Fee(amount=fill['fee'], asset=fill['feeToken']),
    details=fill,
  )


def order_state(order: Any, status: str) -> OrderState:
  sign = 1 if order['side'] == 'B' else -1
  return OrderState(id=str(order['oid']), price=order['limitPx'], qty=sign * order['origSz'], filled_qty=sign * (order['origSz'] - order['sz']), active=status == 'open', details=order)


ADDRESS[:6]

# %% [markdown]
# ## Surface
#
# What the client exposes. Widen or narrow the filter until every endpoint the mapping below uses is listed here.

# %%
from sdk_dev.surface import surface

print(surface('typed_margin_trade', 'MarginTrade', grep=r'spot|book|candle|order|fill|cancel|usd_class'))


# %% [markdown]
# ## `markets`
#
# List available markets: the pair names of `spotMeta`.

# %%
async def markets() -> Sequence[str]:
  return list(await pairs())


await markets(), list(await pairs(public))


# %% [markdown]
# ## `depth`
#
# Fetch the market order book. Testnet's spot book is empty (`levels: [[], []]`); mainnet shows the mapping on real levels.

# %%
async def depth(market_id: str, /, *, levels: int | None = None, settings: Settings = {}, via: MarginTrade = client) -> Book:
  return parse_book(await via.info.l2_book(market_id), levels)


await depth('PRL/USDC'), await depth('PRL/USDC', levels=3, via=public)


# %% [markdown]
# ## `depth_stream`
#
# Subscribe to the market order book (`l2Book`, full snapshots), on mainnet for real levels.

# %%
@asynccontextmanager
async def depth_stream(market_id: str, /, *, levels: int | None = None, queue_size: int = 1, overflow: OverflowPolicy = 'latest', settings: Settings = {}, via: MarginTrade = client) -> AsyncIterator[AsyncIterable[Book]]:
  stream = await via.streams.l2_book(market_id)

  async def books() -> AsyncIterator[Book]:
    async for raw in stream:
      yield parse_book(raw, levels)

  try:
    yield books()
  finally:
    await stream.unsubscribe()


async with depth_stream('PRL/USDC', levels=2, via=public) as stream:
  first = await asyncio.wait_for(anext(aiter(stream)), timeout=30)
first


# %% [markdown]
# ## `tickers`
#
# Fetch a ticker snapshot for many markets at once: 24h volumes from the spot asset contexts, last trade and best bid/ask (no sizes) from the CoinGecko spot tickers, keyed back to the pair by its base and quote token names.

# %%
async def tickers(markets: Collection[str] | None = None, *, settings: Settings = {}, via: MarginTrade = client) -> Mapping[str, Ticker]:
  names = {(base['name'], quote['name']): name for name, (_, base, quote) in (await pairs(via)).items()}
  quotes = {names[(row['base_currency'], row['target_currency'])]: row for row in await via.coingecko.spot.tickers()}
  _, ctxs = await via.info.spot_meta_and_asset_ctxs()
  out: dict[str, Ticker] = {}
  for ctx in ctxs:
    if markets is None or ctx['coin'] in markets:
      quote = quotes.get(ctx['coin'])
      out[ctx['coin']] = Ticker(
        last=quote['last_price'] if quote else None,
        bid=quote.get('bid') if quote else None,
        ask=quote.get('ask') if quote else None,
        base_volume_24h=ctx['dayBaseVlm'],
        quote_volume_24h=ctx['dayNtlVlm'],
      )
  return out


await tickers(), await tickers(via=public), await tickers([])


# %% [markdown]
# ## `rules`
#
# Fetch the market rules: the pair's own `takerFee`/`makerFee` (a mainnet maker fill below was charged exactly `makerFee`), Hyperliquid's spot price precision. The minimums are side-specific (`spotMinBuyQuoteAmount` on buys, `spotMinSellBaseQuantity` on sells; 10 on mainnet, 0 on testnet) and stay in `details`. No fee asset: fills name it per fill.

# %%
async def rules(market_id: str, /, *, refetch: bool = False, via: MarginTrade = client) -> Rules:
  pair, base, _ = (await pairs(via))[market_id]
  sz = base['szDecimals']
  return Rules(
    fee_asset=None,
    tick_size=Decimal(10) ** -min(MAX_SIG_FIGS, SPOT_MAX_DECIMALS - sz),
    step_size=Decimal(10) ** -sz,
    fees=Fees(maker_buy=pair['makerFee'], maker_sell=pair['makerFee'], taker_buy=pair['takerFee'], taker_sell=pair['takerFee']),
    api=True,
    details=pair,
  )


mainnet_fills = await public.info.user_fills(SPOT_TRADER)
spot_fills = [f for f in mainnet_fills if f['coin'] == 'PRL/USDC']
rates = {(f['side'], f['isTaker'], f['feeToken']): f['fee'] / (f['px'] * f['sz']) for f in spot_fills}
await rules('PRL/USDC'), await rules('PRL/USDC', via=public), rates


# %% [markdown]
# ## `fees`
#
# Fetch the selected market's account rates. Not supported, as on perpetuals: `userFees` gives one account-wide spot rate (`userSpotCrossRate`/`userSpotAddRate`, 0.0005/0.0001) while the pair charges its own (`takerFee` 0.0015, `makerFee` -0.0005, matched by the mainnet fill above).

# %%
async def fees(market_id: str, /, *, refetch: bool = False) -> Fees:
  raise NotImplementedError('margin.trade publishes no per-account rate per market')


account = await public.info.user_fees(SPOT_TRADER)
account['userSpotCrossRate'], account['userSpotAddRate']


# %% [markdown]
# ## `candles`
#
# Fetch the market's historical trade candles, as on perpetuals (one request answers the whole 7-day 1m window).

# %%
async def candles(market_id: str, /, interval: CandleInterval, start: datetime, end: datetime, via: MarginTrade = client) -> AsyncIterator[Sequence[Candle]]:
  rows = await via.info.candle_snapshot({'coin': market_id, 'interval': interval, 'startTime': start, 'endTime': end - timedelta(milliseconds=1)})
  page = [Candle(time=r['t'], open=r['o'], high=r['h'], low=r['l'], close=r['c'], volume=r['v'], trades=r['n']) for r in rows if start <= r['t'] < end]
  if page:
    yield page


rows = [c async for p in candles('PRL/USDC', '1h', start, end) for c in p]
main = [c async for p in candles('PRL/USDC', '1h', start, end, via=public) for c in p]
len(rows), rows[-1:], len(main), main[-1:]


# %% [markdown]
# ## `query_order`
#
# Fetch the state of the order with the given ID (`orderStatus`, shared with perpetuals); exercised on a resting spot order in the lifecycle cell.

# %%
async def query_order(market_id: str, /, id: str) -> OrderState | None:
  found = await client.info.order_status(user=ADDRESS, oid=int(id))
  if 'order' in found and found['order']['order']['coin'] == market_id:
    return order_state(found['order']['order'], found['order']['status'])


await query_order('PRL/USDC', '1')


# %% [markdown]
# ## `open_orders`
#
# Fetch your currently open orders (`frontendOpenOrders`, filtered to the pair).

# %%
async def open_orders(market_id: str, /) -> Sequence[OrderState]:
  return [order_state(row, 'open') for row in await client.info.frontend_open_orders(user=ADDRESS) if row['coin'] == market_id]


await open_orders('PRL/USDC')


# %% [markdown]
# ## `trades_history`
#
# Fetch personal fills for one pair or the whole exchange: `userFillsByTime`, keeping the spot pairs. Testnet has none; the mainnet trader's show the mapping.

# %%
async def trades_history(market_id: str | None, /, start: datetime, end: datetime, user: str = ADDRESS, via: MarginTrade = client) -> AsyncIterator[Sequence[Trade]]:
  names = set(await pairs(via))
  async for page in via.info.user_fills_by_time_paged(user, start_time=start, end_time=end):
    if rows := [parse_trade(f) for f in page if f['coin'] in names and (market_id is None or f['coin'] == market_id)]:
      yield rows


testnet = [t async for p in trades_history('PRL/USDC', start, end) for t in p]
mainnet = [t async for p in trades_history(None, start, end, SPOT_TRADER, public) for t in p]
len(testnet), len(mainnet), mainnet[:2], {(t.qty > 0, t.maker, t.fee.asset if t.fee else None) for t in mainnet}


# %% [markdown]
# ## `trades_stream`
#
# Subscribe to your real-time trades: `userFills` with the pair as `coin`. The stream takes any address, so it runs against the mainnet trader. With the client's default 30 s ping the venue drops the socket at ~31 s (see `typed-client-issues.md`), before that trader's next fill, so this cell holds the subscription on a socket built with a 10 s ping, waiting up to ten minutes for one.

# %%
@asynccontextmanager
async def trades_stream(market_id: str, /, *, queue_size: int = 1000, overflow: OverflowPolicy = 'fail', settings: Settings = {}, user: str = ADDRESS, via: MarginTrade = client) -> AsyncIterator[AsyncIterable[Trade]]:
  stream = await via.streams.user_fills(user=user, coin=market_id)

  async def trades() -> AsyncIterator[Trade]:
    async for push in stream:
      if not push.get('isSnapshot'):
        for fill in push['fills']:
          yield parse_trade(fill)

  try:
    yield trades()
  finally:
    await stream.unsubscribe()


from typed_margin_trade.core.transport.ws import SocketClient

streamer = MarginTrade(network=public.network, http=public.http, ws=SocketClient.new(public.network.ws_url, ping_interval=timedelta(seconds=10)))
async with streamer.ws:
  async with trades_stream('PRL/USDC', user=SPOT_TRADER, via=streamer) as stream:
    try:
      print(await asyncio.wait_for(anext(aiter(stream)), timeout=600))
    except asyncio.TimeoutError:
      print('no PRL/USDC fill by the mainnet trader within ten minutes')


# %% [markdown]
# ## `position`
#
# Fetch your position: the base token's spot `total`, resting sells included.

# %%
async def balance(token: int, user: str = ADDRESS, via: MarginTrade = client) -> tuple[Decimal, Decimal]:
  """`(total, hold)` of one spot token; zero when the account has none."""
  for row in (await via.info.spot_clearinghouse_state(user))['balances']:
    if row['token'] == token:
      return row['total'], row['hold']
  return Decimal(0), Decimal(0)


async def position(market_id: str, /, user: str = ADDRESS, via: MarginTrade = client) -> Position:
  _, base, _ = (await pairs(via))[market_id]
  total, _ = await balance(base['index'], user, via)
  return Position(size=total)


await position('PRL/USDC'), await position('PRL/USDC', SPOT_TRADER, public), (await public.info.spot_clearinghouse_state(SPOT_TRADER))['balances']


# %% [markdown]
# ## `collateral`
#
# Fetch the collateral bucket: the quote token's spot balance, free being `total - hold` (what resting buys do not lock).

# %%
async def collateral(market_id: str, /, user: str = ADDRESS, via: MarginTrade = client) -> Collateral:
  _, _, quote = (await pairs(via))[market_id]
  total, hold = await balance(quote['index'], user, via)
  return Collateral(equity=total, free_collateral=total - hold)


await collateral('PRL/USDC'), await collateral('PRL/USDC', SPOT_TRADER, public)


# %% [markdown]
# ## `available_notional`
#
# Fetch the maximum notional you can buy right now: the SDK default, `collateral().free_collateral`.

# %%
async def available_notional(market_id: str, /) -> Decimal:
  return (await collateral(market_id)).free_collateral


await available_notional('PRL/USDC')


# %% [markdown]
# ## `place_order`
#
# Place an order in the pair: asset `10000 + pair index`, otherwise as on perpetuals. Exercised in the lifecycle cell.

# %%
TIF: dict[str, Literal['Gtc', 'Alo', 'Ioc']] = {'LIMIT': 'Gtc', 'POST_ONLY': 'Alo', 'MARKET': 'Ioc'}


async def place_order(market_id: str, /, order: Order, *, settings: Settings = {}) -> OrderResponse:
  pair, base, _ = (await pairs())[market_id]
  qty = Decimal(order['qty'])
  spec: OrderSpec = {'a': SPOT_ASSET_OFFSET + pair['index'], 'b': qty > 0, 'p': round_price(Decimal(order['price']), base['szDecimals']), 's': abs(qty), 'r': False, 't': {'limit': {'tif': TIF[order['type']]}}}
  result = await client.exchange.order([spec], grouping='na')
  status = result['statuses'][0]
  if 'error' in status:
    raise RuntimeError(status['error'])
  if 'resting' in status:
    return OrderResponse(id=str(status['resting']['oid']), details=status)
  return OrderResponse(id=str(status['filled']['oid']), details=status, filled_qty=status['filled']['totalSz'])


place_order  # changes the account: exercised by the lifecycle cell below


# %% [markdown]
# ## `cancel_order`
#
# Cancel an order in the pair. Exercised in the lifecycle cell.

# %%
async def cancel_orders(market_id: str, /, ids: Sequence[str], *, settings: Settings = {}) -> Any:
  if not ids:
    return []
  pair, _, _ = (await pairs())[market_id]
  return (await client.exchange.cancel([{'a': SPOT_ASSET_OFFSET + pair['index'], 'o': int(id)} for id in ids]))['statuses']


async def cancel_order(market_id: str, /, id: str, *, settings: Settings = {}) -> Any:
  status = (await cancel_orders(market_id, [id]))[0]
  if status != 'success':
    raise RuntimeError(status)
  return status


cancel_order  # changes the account: exercised by the lifecycle cell below


# %% [markdown]
# ## `cancel_orders`
#
# Cancel multiple orders in the pair, in one `cancel` action (defined above). Exercised in the lifecycle cell.

# %%
cancel_orders  # changes the account: exercised by the lifecycle cell below


# %% [markdown]
# ## `cancel_open_orders`
#
# Cancel all open orders in the pair. Exercised in the lifecycle cell.

# %%
async def cancel_open_orders(market_id: str, /, *, settings: Settings = {}) -> Any:
  return await cancel_orders(market_id, [o.id for o in await open_orders(market_id)])


cancel_open_orders  # changes the account: exercised by the lifecycle cell below


# %% [markdown]
# ## Lifecycle
#
# On testnet: move 20 USDC perp to spot (signed by the master: `usdClassTransfer` takes micro-USDC, `20000000`), read `collateral`, rest a post-only PRL buy (query, open orders, collateral with the hold, cancel), rest two more and cancel them together, one more for `cancel_open_orders`, then move the 20 USDC back.

# %%
log: dict[str, Any] = {}
await master.exchange.usd_class_transfer('20000000', to_perp=False)
await asyncio.sleep(1)
log['collateral funded'] = await collateral('PRL/USDC')
try:
  bid = await place_order('PRL/USDC', {'type': 'POST_ONLY', 'qty': Decimal('5'), 'price': Decimal('1.23456')})
  log['post_only'] = bid
  await asyncio.sleep(1.5)
  log['query'] = await query_order('PRL/USDC', bid.id)
  log['open'] = await open_orders('PRL/USDC')
  log['collateral held'] = await collateral('PRL/USDC')
  log['available_notional'] = await available_notional('PRL/USDC')
  log['cancel_order'] = await cancel_order('PRL/USDC', bid.id)
  more = [await place_order('PRL/USDC', {'type': 'LIMIT', 'qty': Decimal('2'), 'price': Decimal(p)}) for p in ('1.1', '1.2')]
  log['cancel_orders'] = await cancel_orders('PRL/USDC', [o.id for o in more])
  await place_order('PRL/USDC', {'type': 'LIMIT', 'qty': Decimal('2'), 'price': Decimal('1.15')})
  log['cancel_open_orders'] = await cancel_open_orders('PRL/USDC')
  log['open after'] = await open_orders('PRL/USDC')
finally:
  await cancel_open_orders('PRL/USDC')
  total, _ = await balance(0)
  if total:
    await master.exchange.usd_class_transfer(str(int(total * 10**6)), to_perp=True)
await asyncio.sleep(1)
log['spot after'] = (await client.info.spot_clearinghouse_state(ADDRESS))['balances']
log

# %% [markdown]
# ## Coverage
#
# Status is one of `verified` (executed live, real data), `empty` (executed live, nothing to show on this account), `blocked` (a typed-client issue, numbered in `typed-client-issues.md`), `not supported` (the venue has no such data) or `not attempted`.
#
# | method | status | note |
# |---|---|---|
# | `markets` | verified | `PRL/USDC` on both networks |
# | `depth` | verified | Testnet book empty (`[[], []]`); mainnet levels |
# | `depth_stream` | verified | Mainnet `l2Book` snapshot push |
# | `tickers` | verified | Spot context volumes; CoinGecko last/bid/ask (no sizes), mainnet and testnet |
# | `rules` | verified | Pair `takerFee`/`makerFee` (mainnet maker fills charged exactly -0.0005); tick `10^-min(5, 8 - szDecimals)`; side-specific minimums in `details`; no fee asset |
# | `fees` | not supported | `userFees` spot rates (0.0005/0.0001) differ from the pair rates fills pay |
# | `candles` | verified | 168 one-hour candles over 7 days on both networks |
# | `query_order` | verified | Resting spot post-only buy (lifecycle); unknown id `None` |
# | `open_orders` | verified | Resting buy listed with its signed size |
# | `trades_history` | verified | Mainnet public account: 1433 PRL/USDC fills over 7 days (buys and sells, fees in USDC); testnet none |
# | `trades_stream` | verified | A mainnet trader PRL/USDC maker buy pushed on `userFills`; needed a 10 s ping socket, the client default drops at ~31 s (typed-client issue) |
# | `position` | verified | Mainnet account base total 7429.35 PRL; testnet 0 |
# | `collateral` | verified | 20 testnet USDC moved to spot: free 13.827 while a resting buy held 6.173 |
# | `available_notional` | verified | Free quote balance (SDK default) |
# | `place_order` | verified | `Alo` and `Gtc` buys rest at asset `10000 + index`, price rounded to 1.2346; MARKET not exercised (the testnet spot book has no asks) |
# | `cancel_order` | verified | Resting post-only buy cancelled |
# | `cancel_orders` | verified | Two resting buys in one action |
# | `cancel_open_orders` | verified | One resting buy removed; none open after |

# %% [markdown]
# ## Catalogue
#
# Every ID the verified methods returned, minus what the catalogue translates for this platform. Anything listed is a catalogue addition to make, not something to rename here: the SDK emits venue-native IDs and the catalogue maps them.

# %%
from sdk_dev.catalogue import Ids, gap, load_catalogue

listed = await markets()
tokens = {t['name'] for t in (await client.info.spot_meta())['tokens']}
ids = Ids(spot_markets={f'spot:{m}' for m in listed}, assets=tokens | {t.fee.asset for t in mainnet if t.fee})
gap('margin-trade', ids, load_catalogue(root=repo_root()))

# %%
await client.__aexit__(None, None, None)  # pyright: ignore[reportUnknownMemberType] -- upstream lifecycle parameters are untyped
await public.__aexit__(None, None, None)  # pyright: ignore[reportUnknownMemberType] -- upstream lifecycle parameters are untyped
await master.__aexit__(None, None, None)  # pyright: ignore[reportUnknownMemberType] -- upstream lifecycle parameters are untyped
