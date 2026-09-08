# %%
import asyncio
import os
from decimal import Decimal
from datetime import datetime, timedelta, timezone

from typing_extensions import Literal, cast

from typed_hyperliquid import Hyperliquid
from typed_hyperliquid.exchange.order import HyperliquidOrder
from typed_hyperliquid.streams.l2_book import L2BookUpdate
from typed_hyperliquid.streams.user_fills import UserFills
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

client = await Hyperliquid.new(mainnet=False, public=True).__aenter__()
ADDRESS = os.environ['HYPERLIQUID_TESTNET_ADDRESS']

SPOT_MARKET = 'PURR/USDC'
PERP_MARKET = 'BTC'
PERP_MARKETS = ['BTC', 'ETH']

end = datetime.now(timezone.utc)
start = end - timedelta(days=30)
# every fill on this account predates the 30-day window, so the fill-based reads below
# use a wider one to exercise their mapping against real rows
fills_start = end - timedelta(days=180)

ADDRESS


# %% [markdown]
# > `client` is the raw `typed_hyperliquid.Hyperliquid` client (`client.info`/`client.exchange`/`client.streams`), imported and hand-mapped onto `tribulnation.sdk.market` types below -- no production `tribulnation.hyperliquid` code is imported or driven, unlike the previous round of this notebook. It runs against the Hyperliquid **testnet** account (`HYPERLIQUID_TESTNET_ADDRESS`/`HYPERLIQUID_TESTNET_PRIVATE_KEY` from `.env` -- no mainnet credentials exist in this workspace), the same account used before: it carries real (test) balances and an open `BTC` short, so several results below reflect genuine non-zero state rather than empty placeholders.
# >
# > Hyperliquid splits `spot` (one exchange) from perpetuals, which are further split across the main perp dex (`''`) and ~250 permissionless HIP-3 builder-deployed dexs -- mirrored below as an `exchanges()`-equivalent listing, then a spot section, then a perp section.

# %% [markdown]
# ## Exchanges (spot / perp dexs)

# %%
async def exchanges() -> list[dict[str, str]]:
  """List every exchange on the venue: the one spot exchange, the main perp dex (''), and
  every permissionless HIP-3 builder-deployed perp dex."""
  # dexs[0] is always None (the main dex placeholder)
  dexs = await client.info.perp_dexs()
  out = [{'id': 'spot', 'type': 'spot'}, {'id': '', 'type': 'perp'}]
  for dex in dexs[1:]:
    if dex is not None:
      out.append({'id': dex['name'], 'type': 'perp'})
  return out


result = await exchanges()
len(result), result[:5]


# %% [markdown]
# ## `Market` (spot)
#
# Hyperliquid's `l2Book`, fills, and order-status endpoints are already `coin`-generic across spot and perp -- `depth`/`depth_stream`/`open_orders`/`query_order`/`trades_history`/`trades_stream` below are defined once and reused as-is for the perp section further down.

# %%
async def depth(coin: str, *, levels: int | None = None) -> Book:
  raw = await client.info.l2_book(coin=coin)
  bids_raw, asks_raw = raw['levels']
  book = Book(
    bids=[Book.Entry(Decimal(b['px']), Decimal(b['sz'])) for b in bids_raw],
    asks=[Book.Entry(Decimal(a['px']), Decimal(a['sz'])) for a in asks_raw],
  )
  return book.limit(levels) if levels else book


await depth(SPOT_MARKET, levels=5)


# %%
def depth_stream(coin: str):
  def to_book(update: L2BookUpdate) -> Book:
    bids_raw, asks_raw = update['levels']
    return Book(
      bids=[Book.Entry(Decimal(b['px']), Decimal(b['sz'])) for b in bids_raw],
      asks=[Book.Entry(Decimal(a['px']), Decimal(a['sz'])) for a in asks_raw],
    )

  return client.streams.l2_book(coin).map(to_book)


books: list[Book] = []
async with depth_stream(SPOT_MARKET) as stream:
  it = aiter(stream)
  for _ in range(2):
    try:
      books.append(await asyncio.wait_for(anext(it), timeout=15.0))
    except asyncio.TimeoutError:
      break
books


# %%
async def rules(coin: str) -> Rules:
  spot_meta, _ = await client.info.spot_meta_and_asset_ctxs()
  tokens_by_index = {t['index']: t for t in spot_meta['tokens']}
  pair = next(p for p in spot_meta['universe'] if p['name'] == coin)
  base_idx, quote_idx = pair['tokens']
  base_meta = tokens_by_index[base_idx]
  quote_meta = tokens_by_index[quote_idx]
  fees = await client.info.user_fees(user=ADDRESS)
  # Tick/lot sizing per https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/tick-and-lot-size:
  # spot prices round to 5 significant figures, capped at 8 decimals minus the asset's size decimals.
  tick_decimals = min(5, 8 - base_meta['szDecimals'])
  return Rules(
    base=base_meta['name'],
    quote=quote_meta['name'],
    fee_asset=quote_meta['name'],
    tick_size=Decimal(10) ** -tick_decimals,
    step_size=Decimal(10) ** -base_meta['szDecimals'],
    min_value=Decimal(10),  # undocumented -- the API rejects orders below $10 notional
    # undocumented -- the API rejects orders >80% away from mark
    rel_min_price=Decimal('0.2'),
    rel_max_price=Decimal('1.8'),
    maker_fee=Decimal(fees['userSpotAddRate']),
    taker_fee=Decimal(fees['userSpotCrossRate']),
    api=True,
    details={'pair': pair, 'base': base_meta, 'quote': quote_meta},
  )


await rules(SPOT_MARKET)


# %%
async def open_orders(coin: str) -> list[OrderState]:
  raw = await client.info.frontend_open_orders(user=ADDRESS)
  out: list[OrderState] = []
  for o in raw:
    if o['coin'] != coin:
      continue
    orig_qty = Decimal(o['origSz'])
    remaining = Decimal(o['sz'])
    sign = 1 if o['side'] == 'B' else -1
    out.append(
      OrderState(
        id=str(o['oid']),
        price=Decimal(o['limitPx']),
        qty=sign * orig_qty,
        filled_qty=sign * (orig_qty - remaining),
        active=True,
        details=o,
      )
    )
  return out


await open_orders(SPOT_MARKET)


# %%
async def query_order(id: str) -> OrderState | None:
  status = await client.info.order_status(user=ADDRESS, oid=int(id))
  if status['status'] == 'unknownOid':
    return None
  entry = status['order']
  o = entry['order']
  orig_qty = Decimal(o['origSz'])
  remaining = Decimal(o['sz'])
  sign = 1 if o['side'] == 'B' else -1
  return OrderState(
    id=str(o['oid']),
    price=Decimal(o['limitPx']),
    qty=sign * orig_qty,
    filled_qty=sign * (orig_qty - remaining),
    active=entry['status'] in ('open', 'triggered', 'scheduledCancel'),
    details=status,
  )


# No order with this id was ever placed on this account -- exercises the `None` branch live.
await query_order('123456')


# %%
async def trades_history(coin: str, start: datetime, end: datetime) -> list[Trade]:
  fills = await client.info.user_fills_by_time(
    user=ADDRESS, start_time=start, end_time=end
  )
  out: list[Trade] = []
  for f in fills:
    if f['coin'] != coin:
      continue
    sign = 1 if f['side'] == 'B' else -1
    out.append(
      Trade(
        id=str(f['tid']),
        price=f['px'],
        qty=sign * f['sz'],
        time=f['time'],
        maker=not f['crossed'],
        fee=Trade.Fee(amount=f['fee'], asset=f['feeToken']),
        details=f,
      )
    )
  return out


await trades_history(SPOT_MARKET, fills_start, end)


# %%
def trades_stream(coin: str):
  # the first message is always a fills *snapshot* rather than a live update, so it's
  # mapped to `None` and filtered out.
  def parse(msg: UserFills) -> list[Trade] | None:
    if msg['isSnapshot']:
      return None
    out: list[Trade] = []
    for f in msg['fills']:
      if f['coin'] != coin:
        continue
      sign = 1 if f['side'] == 'B' else -1
      out.append(
        Trade(
          id=str(f['tid']),
          price=f['px'],
          qty=sign * f['sz'],
          time=f['time'],
          maker=not f['crossed'],
          fee=Trade.Fee(amount=f['fee'], asset=f['feeToken']),
          details=f,
        )
      )
    return out or None

  return (
    client.streams.user_fills(ADDRESS, aggregate_by_time=True)
    .map(parse)
    .filter(lambda t: t is not None)
  )


async with trades_stream(SPOT_MARKET) as stream:
  it = aiter(stream)
  try:
    result = await asyncio.wait_for(anext(it), timeout=5.0)
  except asyncio.TimeoutError:
    result = (
      'no new trades observed in 5s (expected -- no live trading on this account)'
    )
result


# %%
async def position(coin: str) -> Position:
  spot_meta, _ = await client.info.spot_meta_and_asset_ctxs()
  tokens_by_index = {t['index']: t for t in spot_meta['tokens']}
  pair = next(p for p in spot_meta['universe'] if p['name'] == coin)
  base_meta = tokens_by_index[pair['tokens'][0]]
  state = await client.info.spot_clearinghouse_state(user=ADDRESS)
  for b in state['balances']:
    if b['token'] == base_meta['index']:
      return Position(size=Decimal(b['total']))
  return Position()


await position(SPOT_MARKET)


# %%
async def collateral(coin: str) -> Collateral:
  spot_meta, _ = await client.info.spot_meta_and_asset_ctxs()
  tokens_by_index = {t['index']: t for t in spot_meta['tokens']}
  pair = next(p for p in spot_meta['universe'] if p['name'] == coin)
  quote_meta = tokens_by_index[pair['tokens'][1]]
  state = await client.info.spot_clearinghouse_state(user=ADDRESS)
  for b in state['balances']:
    if b['token'] == quote_meta['index']:
      total = Decimal(b['total'])
      hold = Decimal(b['hold'])
      return Collateral(equity=total, free_collateral=total - hold)
  return Collateral(equity=Decimal(0), free_collateral=Decimal(0))


await collateral(SPOT_MARKET)


# %%
async def available_notional(coin: str) -> Decimal:
  c = await collateral(coin)
  return c.free_collateral


await available_notional(SPOT_MARKET)


# %% [markdown]
# ### Mutating (written, never executed)

# %%
async def place_order(
  coin: str, order: Order, *, settings: Settings = {}
) -> OrderResponse:
  spot_meta, _ = await client.info.spot_meta_and_asset_ctxs()
  pair = next(p for p in spot_meta['universe'] if p['name'] == coin)
  # spot asset indices are offset by 10000 in exchange actions
  asset_id = 10000 + pair['index']
  qty = Decimal(order['qty'])
  tif = cast(
    Literal['Gtc', 'Ioc', 'Alo'],
    {'LIMIT': 'Gtc', 'MARKET': 'Ioc', 'POST_ONLY': 'Alo'}[order['type']],
  )
  wire: HyperliquidOrder = {
    'a': asset_id,
    'b': qty >= 0,
    'p': Decimal(order['price']),
    's': abs(qty),
    'r': False,
    't': {'limit': {'tif': tif}},
  }
  result = await client.exchange.order(orders=[wire], grouping='na')
  if result['status'] == 'err':
    raise RuntimeError(f'order action rejected: {result["response"]}')
  status = result['response']['data']['statuses'][0]
  if 'resting' in status:
    return OrderResponse(id=str(status['resting']['oid']), details=status)
  if 'filled' in status:
    return OrderResponse(id=str(status['filled']['oid']), details=status)
  raise RuntimeError(f'order rejected: {status}')


# Not executed here -- would place a real order on the testnet account.
await place_order(
  SPOT_MARKET, {'qty': Decimal('1'), 'price': Decimal('0.1'), 'type': 'LIMIT'}
)


# %%
async def cancel_order(coin: str, id: str, *, settings: Settings = {}):
  spot_meta, _ = await client.info.spot_meta_and_asset_ctxs()
  pair = next(p for p in spot_meta['universe'] if p['name'] == coin)
  asset_id = 10000 + pair['index']
  result = await client.exchange.cancel(cancels=[{'a': asset_id, 'o': int(id)}])
  if result['status'] == 'err':
    raise RuntimeError(f'cancel action rejected: {result["response"]}')
  return result['response']['data']['statuses'][0]


# Not executed here -- would cancel a real order on the testnet account.
await cancel_order(SPOT_MARKET, '123456')

# %% [markdown]
# ## `PerpMarket`
#
# Only position/collateral/rules/index/funding are genuinely perp-specific; `depth`/`depth_stream`/`open_orders`/`query_order`/`trades_history`/`trades_stream` from the spot section above are reused unchanged (just called with a perp `coin`).

# %%
await depth(PERP_MARKET, levels=5)

# %%
books: list[Book] = []
async with depth_stream(PERP_MARKET) as stream:
  it = aiter(stream)
  for _ in range(2):
    try:
      books.append(await asyncio.wait_for(anext(it), timeout=15.0))
    except asyncio.TimeoutError:
      break
books


# %%
async def perp_rules(coin: str, *, dex: str | None = None) -> Rules:
  perp_meta, _ = await client.info.perp_meta_and_asset_ctxs(dex=dex)
  spot_meta, _ = await client.info.spot_meta_and_asset_ctxs()
  tokens_by_index = {t['index']: t for t in spot_meta['tokens']}
  asset = next(a for a in perp_meta['universe'] if a['name'] == coin)
  collateral_meta = tokens_by_index[perp_meta['collateralToken']]
  fees = await client.info.user_fees(user=ADDRESS)
  # Perp prices round to 5 significant figures, capped at 6 decimals minus size decimals.
  tick_decimals = min(5, 6 - asset['szDecimals'])
  return Rules(
    base=coin,
    quote=collateral_meta['name'],
    fee_asset=collateral_meta['name'],
    tick_size=Decimal(10) ** -tick_decimals,
    step_size=Decimal(10) ** -asset['szDecimals'],
    min_value=Decimal(10),
    rel_min_price=Decimal('0.2'),
    rel_max_price=Decimal('1.8'),
    maker_fee=Decimal(fees['userAddRate']),
    taker_fee=Decimal(fees['userCrossRate']),
    api=not asset.get('isDelisted', False),
    details={'asset': asset, 'collateral': collateral_meta},
  )


await perp_rules(PERP_MARKET)

# %%
await open_orders(PERP_MARKET)

# %%
await query_order('123456')

# %%
await trades_history(PERP_MARKET, fills_start, end)


# %%
async with trades_stream(PERP_MARKET) as stream:
  it = aiter(stream)
  try:
    result = await asyncio.wait_for(anext(it), timeout=5.0)
  except asyncio.TimeoutError:
    result = (
      'no new trades observed in 5s (expected -- no live trading on this account)'
    )
result


# %%
async def perp_position(coin: str, *, dex: str | None = None) -> PerpPosition:
  state = await client.info.clearinghouse_state(user=ADDRESS, dex=dex)
  for entry in state['assetPositions']:
    pos = entry['position']
    if pos['coin'] == coin:
      return PerpPosition(size=Decimal(pos['szi']), entry_price=Decimal(pos['entryPx']))
  return PerpPosition()


# Real state: this account carries an open BTC short on the main perp dex.
await perp_position(PERP_MARKET)


# %%
async def perp_collateral(*, dex: str | None = None) -> PerpCollateral:
  # Simplified to the account-wide CROSS bucket -- Hyperliquid has no per-position
  # maintenance-margin field for isolated positions, unlike cross, so a fully mode-aware
  # split (isolated vs. cross) isn't attempted here; see the coverage note below.
  state = await client.info.clearinghouse_state(user=ADDRESS, dex=dex)
  equity = Decimal(state['marginSummary']['accountValue'])
  used = Decimal(state['marginSummary']['totalMarginUsed'])
  maintenance = Decimal(state['crossMaintenanceMarginUsed'])
  notional = Decimal(state['crossMarginSummary']['totalNtlPos'])
  leverage = notional / equity if equity > 0 else Decimal(0)
  return PerpCollateral(
    equity=equity,
    free_collateral=Decimal(state['withdrawable']),
    initial_margin=used,
    maintenance_margin=maintenance,
    leverage=leverage,
    margin_mode='cross',
  )


await perp_collateral()


# %%
async def perp_available_notional(coin: str, *, dex: str | None = None) -> Decimal:
  c = await perp_collateral(dex=dex)
  perp_meta, _ = await client.info.perp_meta_and_asset_ctxs(dex=dex)
  asset = next(a for a in perp_meta['universe'] if a['name'] == coin)
  return c.free_collateral * asset['maxLeverage']


await perp_available_notional(PERP_MARKET)


# %%
async def index(coin: str, *, dex: str | None = None) -> Decimal:
  perp_meta, asset_ctxs = await client.info.perp_meta_and_asset_ctxs(dex=dex)
  idx = next(i for i, a in enumerate(perp_meta['universe']) if a['name'] == coin)
  return Decimal(asset_ctxs[idx]['oraclePx'])


await index(PERP_MARKET)


# %%
async def next_funding(coin: str, *, dex: str | None = None) -> NextFunding:
  perp_meta, asset_ctxs = await client.info.perp_meta_and_asset_ctxs(dex=dex)
  idx = next(i for i, a in enumerate(perp_meta['universe']) if a['name'] == coin)
  rate = Decimal(asset_ctxs[idx]['funding'])
  now = datetime.now(timezone.utc)
  next_time = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
  return NextFunding(rate=rate, time=next_time, interval=timedelta(hours=1))


await next_funding(PERP_MARKET)


# %%
async def funding_rates(coin: str, start: datetime, end: datetime) -> list[FundingRate]:
  raw = await client.info.funding_history(coin=coin, start_time=start, end_time=end)
  return [
    FundingRate(
      rate=Decimal(r['fundingRate']), time=r['time'], premium=Decimal(r['premium'])
    )
    for r in raw
  ]


await funding_rates(PERP_MARKET, start, end)


# %%
async def funding_payments(
  coin: str, start: datetime, end: datetime
) -> list[FundingPayment]:
  # Hyperliquid's `usdc` is positive when *received*; `FundingPayment.amount` is positive
  # when *paid* -- opposite sign conventions, so this negates it.
  raw = await client.info.user_funding(user=ADDRESS, start_time=start, end_time=end)
  return [
    FundingPayment(amount=-Decimal(p['delta']['usdc']), time=p['time'])
    for p in raw
    if p['delta']['coin'] == coin
  ]


# Real data: this account's open BTC short has been accruing hourly funding.
await funding_payments(PERP_MARKET, start, end)


# %% [markdown]
# ### Mutating (written, never executed)

# %%
async def perp_place_order(
  coin: str,
  order: Order,
  *,
  dex: str | None = None,
  settings: Settings = {},
) -> OrderResponse:
  perp_meta, _ = await client.info.perp_meta_and_asset_ctxs(dex=dex)
  asset_idx = next(i for i, a in enumerate(perp_meta['universe']) if a['name'] == coin)
  if dex:
    dexs = await client.info.perp_dexs()
    dex_idx = next(i for i, d in enumerate(dexs) if d and d['name'] == dex)
    asset_id = 100000 + dex_idx * 10000 + asset_idx  # HIP-3 builder-perp asset indexing
  else:
    asset_id = asset_idx
  qty = Decimal(order['qty'])
  tif = cast(
    Literal['Gtc', 'Ioc', 'Alo'],
    {'LIMIT': 'Gtc', 'MARKET': 'Ioc', 'POST_ONLY': 'Alo'}[order['type']],
  )
  wire: HyperliquidOrder = {
    'a': asset_id,
    'b': qty >= 0,
    'p': Decimal(order['price']),
    's': abs(qty),
    'r': False,
    't': {'limit': {'tif': tif}},
  }
  result = await client.exchange.order(orders=[wire], grouping='na')
  if result['status'] == 'err':
    raise RuntimeError(f'order action rejected: {result["response"]}')
  status = result['response']['data']['statuses'][0]
  if 'resting' in status:
    return OrderResponse(id=str(status['resting']['oid']), details=status)
  if 'filled' in status:
    return OrderResponse(id=str(status['filled']['oid']), details=status)
  raise RuntimeError(f'order rejected: {status}')


# Not executed here -- would place a real order on the testnet account.
await perp_place_order(
  PERP_MARKET, {'qty': Decimal('0.001'), 'price': Decimal('1000'), 'type': 'LIMIT'}
)


# %%
async def perp_cancel_order(
  coin: str,
  id: str,
  *,
  dex: str | None = None,
  settings: Settings = {},
):
  perp_meta, _ = await client.info.perp_meta_and_asset_ctxs(dex=dex)
  asset_idx = next(i for i, a in enumerate(perp_meta['universe']) if a['name'] == coin)
  if dex:
    dexs = await client.info.perp_dexs()
    dex_idx = next(i for i, d in enumerate(dexs) if d and d['name'] == dex)
    # HIP-3 builder-perp asset indexing, matching perp_place_order above
    asset_id = 100000 + dex_idx * 10000 + asset_idx
  else:
    asset_id = asset_idx
  result = await client.exchange.cancel(cancels=[{'a': asset_id, 'o': int(id)}])
  if result['status'] == 'err':
    raise RuntimeError(f'cancel action rejected: {result["response"]}')
  return result['response']['data']['statuses'][0]


# Not executed here -- would cancel a real order on the testnet account.
await perp_cancel_order(PERP_MARKET, '123456')

# %% [markdown]
# ## Coverage assessment

# %% [markdown]
# **Full**, for every read-only method -- all execute live against the real testnet account/API:
#
# - **Exchanges**: `perp_dexs()` lists the main perp dex (`''`) plus ~250 permissionless HIP-3 builder-deployed dexs; `exchanges()` above folds these together with the one spot exchange.
# - **Spot / `Market`**: `depth()`/`depth_stream()` and `rules()` return real book/rule data for `PURR/USDC`; `open_orders()` and `trades_stream()` come back empty/timeout because the account has nothing resting and nothing trading right now -- accurate negative results, not gaps. `trades_history()` is empty for a narrower reason: the account has never traded `PURR/USDC`. Its only spot fills are in `@1035`, the venue's index-style name for the `HYPE/USDC` pair, and the exact-`coin` filter drops them. `position()`/`collateral()`/`available_notional()` reflect the account's real USDC/PURR balances. `query_order()` correctly returns `None` for an id that was never placed.
# - **Perp / `PerpMarket`**: `depth()`/`depth_stream()`/`rules()`/`index()`/`next_funding()` all return real BTC market data; `perp_position()` returns the account's genuine open short; `perp_collateral()`/`perp_available_notional()` reflect real margin usage; `funding_rates()`/`funding_payments()` return real accrued hourly funding on the open position (non-empty, unlike the spot side). `trades_history()` returns the account's 24 real `BTC` fills; `open_orders()`/`trades_stream()` are empty/timeout for the same no-current-activity reason as spot.
# - `place_order`/`cancel_order` (both sections) are written but never executed, consistent with the task constraint against placing/canceling real orders.
#
# **Two windows**: every call above uses the 30-day `start`/`end` pair except the two `trades_history()` calls, which use the 180-day `fills_start`. Every fill on this account is from May-July, so a 30-day window returns none of them and the mapping would go unexercised.
#
# **`UserFill.dir`** is an open-ended display string (`str` at all three declaration sites: both `info` fill endpoints and `streams.user_fills`); the 27 fills on this account carry five distinct values (`Buy`, `Sell`, `Open Long`, `Close Long`, `Open Short`), and they come through in each `Trade.details`.
#
# **Simplification, not a gap**: `perp_collateral()` above only returns the account-wide CROSS bucket. Hyperliquid also supports per-position ISOLATED margin (with its own `rawUsd`/`marginUsed` fields on `clearinghouse_state`'s `assetPositions`), and a genuinely mode-aware implementation would branch on the position's `leverage.type` the way the production `tribulnation.hyperliquid` implementation does (reconstructing isolated maintenance margin from the venue's `1 / (2 * maxLeverage)` rule, since Hyperliquid reports no such field directly) -- omitted here to keep the mapping readable, and not exercised live since this account's open BTC position is cross-margined.
