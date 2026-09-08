# %% [markdown]
# # Bitget `market` -- gap check (UTA)
#
# Same rationale as `market/classic.ipynb`: production has no `Market`/`PerpMarket`
# implementation, but `uta.market`/`uta.trade`/`uta.position` are real, confirmed trading
# surfaces. Split by account mode for the same reason as `earn`/`wallet`/`reporting`:
# UTA's `place`/`cancel`/`unfilled`/`fills` all key off one `category` (`SPOT`, `MARGIN`,
# `USDT-FUTURES`, `COIN-FUTURES`, `USDC-FUTURES`) against ONE unified collateral pool
# (`account.assets()`), a structurally different trading/collateral model than Classic's
# per-product-line balances -- not just a credential swap.

# %%
import asyncio
import os
from decimal import Decimal
from datetime import datetime, timedelta, timezone

from typed_bitget import Bitget
from typed_bitget.uta.trade.order.place import LimitOrderRequest, MarketOrderRequest
from dotenv import load_dotenv

from tribulnation.sdk.market import (
  Book,
  Collateral,
  FundingPayment,
  FundingRate,
  NextFunding,
  Order,
  OrderResponse,
  OrderState,
  PerpCollateral,
  PerpPosition,
  Position,
  Rules,
  Settings,
  Trade,
)

load_dotenv()

client = await Bitget.new(
  access_key=os.environ['BITGET_UTA_ACCESS_KEY'],
  secret_key=os.environ['BITGET_UTA_SECRET_KEY'],
  passphrase=os.environ['BITGET_UTA_PASSPHRASE'],
).__aenter__()

SPOT_MARKETS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']
PERP_MARKETS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']
PERP_CATEGORY = 'USDT-FUTURES'


# %% [markdown]
# ## `Market` (UTA, category `SPOT`)

# %%
async def depth(symbol: str, *, levels: int | None = None) -> Book:
  raw = await client.uta.market.orderbook(category='SPOT', symbol=symbol, limit=levels)
  return Book(
    bids=[Book.Entry(Decimal(str(p)), Decimal(str(q))) for p, q in raw['b']],
    asks=[Book.Entry(Decimal(str(p)), Decimal(str(q))) for p, q in raw['a']],
  )

{symbol: await depth(symbol, levels=5) for symbol in SPOT_MARKETS}


# %% [markdown]
# `rules()` below leaves `maker_fee`/`taker_fee` at `0`: unlike Classic's `SpotSymbol`,
# `uta.market.instruments`'s spot rows carry no fee-rate fields at all. Both are declared
# `NotRequired` and documented "futures only", and the live `SPOT` rows for all three
# symbols below confirm it -- they carry `pricePrecision`/`quantityPrecision`/
# `minOrderQty`/`minOrderAmount`/`status` and no `makerFeeRate`/`takerFeeRate`, while the
# same call for `USDT-FUTURES` returns both. No alternative UTA spot-fee-rate endpoint was
# found in scope.

# %%
async def rules(symbol: str, *, refetch: bool = False) -> Rules:
  raw = await client.uta.market.instruments(category='SPOT', symbol=symbol)
  s = raw[0]
  return Rules(
    base=s['baseCoin'],
    quote=s['quoteCoin'],
    fee_asset=s['quoteCoin'],
    tick_size=Decimal(10) ** -int(s['pricePrecision']),
    step_size=Decimal(10) ** -int(s['quantityPrecision']),
    fixed_min_qty=s['minOrderQty'],
    min_value=s['minOrderAmount'],
    max_qty=s['maxOrderQty'],
    maker_fee=s.get('makerFeeRate') or Decimal(0),
    taker_fee=s.get('takerFeeRate') or Decimal(0),
    api=s['status'] in ('listed', 'online'),
    details=s,
  )

{symbol: await rules(symbol) for symbol in SPOT_MARKETS}


# %%
async def open_orders(symbol: str) -> list[OrderState]:
  raw = await client.uta.trade.order.unfilled(category='SPOT', symbol=symbol)
  out: list[OrderState] = []
  for o in raw['list'] or []:
    qty = Decimal(o['qty'])
    filled = Decimal(o['cumExecQty'])
    sign = 1 if o['side'] == 'buy' else -1
    out.append(OrderState(
      id=o['orderId'],
      price=Decimal(o['price']),
      qty=sign * qty,
      filled_qty=sign * filled,
      active=True,  # this endpoint only lists currently-unfilled orders
      details=o,
    ))
  return out

{symbol: await open_orders(symbol) for symbol in SPOT_MARKETS}


# %%
async def trades_history(symbol: str, start: datetime, end: datetime) -> list[Trade]:
  raw = await client.uta.trade.order.fills(
    category='SPOT', start_time=start, end_time=end,
  )
  out: list[Trade] = []
  for f in raw['list'] or []:
    if f['symbol'] != symbol:
      continue
    qty = Decimal(f['execQty'])
    fee = None
    if f['feeDetail']:
      fee_amount = sum(abs(Decimal(d['fee'])) for d in f['feeDetail'])
      if fee_amount:
        fee = Trade.Fee(amount=fee_amount, asset=f['feeDetail'][0]['feeCoin'])
    out.append(Trade(
      id=f['execId'],
      price=Decimal(f['execPrice']),
      qty=qty if f['side'] == 'buy' else -qty,
      time=f['createdTime'],
      maker=f['tradeScope'].lower() == 'maker',
      fee=fee,
      details=f,
    ))
  return out

end = datetime.now(timezone.utc)
start = end - timedelta(hours=24)
{symbol: await trades_history(symbol, start, end) for symbol in SPOT_MARKETS}


# %% [markdown]
# `position()`/`available_notional()` both read the *same* `account.assets()` call UTA
# uses for its overall collateral (see `reporting/uta.ipynb`'s `Snapshots` section) --
# there's no separate "spot balance" endpoint the way Classic has `spot.account.assets`,
# because UTA doesn't partition spot balances from the rest of the unified account.

# %%
async def coin_balance(coin: str) -> Decimal:
  raw = await client.uta.account.assets()
  row = next((a for a in raw['assets'] if a['coin'] == coin), None)
  return row['balance'] if row else Decimal(0)


async def position(symbol: str) -> Position:
  base = symbol.removesuffix('USDT')  # SPOT_MARKETS are all *USDT pairs here
  return Position(size=await coin_balance(base))

{symbol: await position(symbol) for symbol in SPOT_MARKETS}


# %%
async def available_notional(symbol: str) -> Decimal:
  return await coin_balance('USDT')

{symbol: await available_notional(symbol) for symbol in SPOT_MARKETS}


# %%
async def place_order(symbol: str, order: Order, *, settings: Settings = {}) -> OrderResponse:
  qty_signed = Decimal(str(order['qty']))
  side = 'buy' if qty_signed > 0 else 'sell'
  qty = abs(qty_signed)
  price = Decimal(str(order['price']))
  body: LimitOrderRequest | MarketOrderRequest
  if order['type'] == 'MARKET':
    body = {'category': 'SPOT', 'symbol': symbol, 'side': side, 'qty': qty, 'orderType': 'market'}
  else:
    time_in_force = 'post_only' if order['type'] == 'POST_ONLY' else 'gtc'
    body = {
      'category': 'SPOT', 'symbol': symbol, 'side': side, 'qty': qty,
      'orderType': 'limit', 'price': price, 'timeInForce': time_in_force,
    }
  raw = await client.uta.trade.order.place(body)
  return OrderResponse(id=raw['orderId'], details=raw)

# Not executed here -- would place a real order on the account.
await place_order('BTCUSDT', {'qty': Decimal('0.0001'), 'price': Decimal('20000'), 'type': 'LIMIT'})


# %%
async def cancel_order(symbol: str, id: str, *, settings: Settings = {}):
  return await client.uta.trade.order.cancel(order_id=id, category='SPOT')

# Not executed here -- would cancel a real order on the account.
await cancel_order('BTCUSDT', '123456')


# %% [markdown]
# ### Coverage assessment: `Market` (UTA spot)
#
# **Mostly supported.** `depth`, `open_orders`, `trades_history`, `position`,
# `available_notional`, `place_order`, `cancel_order` all map cleanly (confirmed against
# real live responses: the unified account holds USDT/USDC/XRP/BGB dust, has no unfilled
# spot orders, and no spot fills in the last 24 hours). The one real gap:
# `rules().maker_fee`/`taker_fee` have no source under `uta.market.instruments` for `SPOT`
# rows (see the note above) -- left at `0` rather than guessed. `collateral()` is left
# unimplemented, same choice as Classic's spot section.

# %% [markdown]
# ## `PerpMarket` (UTA, category `USDT-FUTURES`)

# %%
async def perp_depth(symbol: str, *, levels: int | None = None) -> Book:
  raw = await client.uta.market.orderbook(category=PERP_CATEGORY, symbol=symbol, limit=levels)
  return Book(
    bids=[Book.Entry(Decimal(str(p)), Decimal(str(q))) for p, q in raw['b']],
    asks=[Book.Entry(Decimal(str(p)), Decimal(str(q))) for p, q in raw['a']],
  )

{symbol: await perp_depth(symbol, levels=5) for symbol in PERP_MARKETS}


# %%
async def perp_rules(symbol: str, *, refetch: bool = False) -> Rules:
  raw = await client.uta.market.instruments(category=PERP_CATEGORY, symbol=symbol)
  s = raw[0]
  return Rules(
    base=s['baseCoin'],
    quote=s['quoteCoin'],
    fee_asset=s['quoteCoin'],
    tick_size=Decimal(10) ** -int(s['pricePrecision']),
    step_size=Decimal(10) ** -int(s['quantityPrecision']),
    fixed_min_qty=s['minOrderQty'],
    min_value=s['minOrderAmount'],
    max_qty=s['maxOrderQty'],
    maker_fee=s.get('makerFeeRate') or Decimal(0),
    taker_fee=s.get('takerFeeRate') or Decimal(0),
    api=s['status'] in ('listed', 'online'),
    details=s,
  )

{symbol: await perp_rules(symbol) for symbol in PERP_MARKETS}


# %%
async def perp_open_orders(symbol: str) -> list[OrderState]:
  raw = await client.uta.trade.order.unfilled(category=PERP_CATEGORY, symbol=symbol)
  out: list[OrderState] = []
  for o in raw['list'] or []:
    qty = Decimal(o['qty'])
    filled = Decimal(o['cumExecQty'])
    sign = 1 if o['side'] == 'buy' else -1
    out.append(OrderState(
      id=o['orderId'],
      price=Decimal(o['price']),
      qty=sign * qty,
      filled_qty=sign * filled,
      active=True,
      details=o,
    ))
  return out

{symbol: await perp_open_orders(symbol) for symbol in PERP_MARKETS}


# %%
async def perp_trades_history(symbol: str, start: datetime, end: datetime) -> list[Trade]:
  raw = await client.uta.trade.order.fills(
    category=PERP_CATEGORY, start_time=start, end_time=end,
  )
  out: list[Trade] = []
  for f in raw['list'] or []:
    if f['symbol'] != symbol:
      continue
    qty = Decimal(f['execQty'])
    fee = None
    if f['feeDetail']:
      fee_amount = sum(abs(Decimal(d['fee'])) for d in f['feeDetail'])
      if fee_amount:
        fee = Trade.Fee(amount=fee_amount, asset=f['feeDetail'][0]['feeCoin'])
    out.append(Trade(
      id=f['execId'],
      price=Decimal(f['execPrice']),
      qty=qty if f['side'] == 'buy' else -qty,
      time=f['createdTime'],
      maker=f['tradeScope'].lower() == 'maker',
      fee=fee,
      details=f,
    ))
  return out

{symbol: await perp_trades_history(symbol, start, end) for symbol in PERP_MARKETS}


# %%
async def index(symbol: str, *, settings: Settings = {}) -> Decimal:
  raw = await client.uta.market.tickers(category=PERP_CATEGORY, symbol=symbol)
  price = raw[0].get('indexPrice')
  if price is None:
    raise NotImplementedError(f'{symbol}: `tickers` carries no `indexPrice` for {PERP_CATEGORY}')
  return price

{symbol: await index(symbol) for symbol in PERP_MARKETS}


# %%
async def next_funding(symbol: str) -> NextFunding:
  raw = await client.uta.market.funding_rate.current(category=PERP_CATEGORY, symbol=symbol)
  r = raw[0]
  return NextFunding(
    rate=Decimal(r['fundingRate']),
    time=r['nextUpdate'],
    interval=timedelta(hours=int(r['fundingRateInterval'])),
  )

{symbol: await next_funding(symbol) for symbol in PERP_MARKETS}


# %%
async def funding_rates(
  symbol: str, start: datetime | None = None, end: datetime | None = None,
) -> list[FundingRate]:
  # `funding_rate.history`'s `cursor` behaves as a page number, not a date range -- one
  # page is fetched and filtered client-side, same caveat as `market/classic.ipynb`.
  raw = await client.uta.market.funding_rate.history(category=PERP_CATEGORY, symbol=symbol, limit=50)
  out = [FundingRate(rate=r['fundingRate'], time=r['fundingRateTimestamp']) for r in raw['resultList']]
  if start is not None:
    out = [r for r in out if r.time >= start]
  if end is not None:
    out = [r for r in out if r.time <= end]
  return out

funding_end = datetime.now(timezone.utc)
funding_start = funding_end - timedelta(days=7)
{symbol: await funding_rates(symbol, funding_start, funding_end) for symbol in PERP_MARKETS}


# %% [markdown]
# ### `funding_payments` -- not supported
#
# Same gap as `market/classic.ipynb`: no dedicated funding-fee endpoint under `uta.*`, and
# the ledger that would carry the payments, `uta.account.financial_records`, filters on a
# free-text `type` the venue documents as open-ended (an RWA cash-dividend value was added
# in 2026-06) without listing the values. Walking this account's whole reachable ledger
# (the endpoint refuses a start time more than ~90 days back) turned up four values --
# `ORDER_DEALT_IN`, `ORDER_DEALT_FROZEN_OUT`, `BUY_DEAL`, `SELL_DEAL` -- none of them a
# funding settlement. Rather than guess a substring filter, the method raises.

# %%
async def funding_payments(symbol: str, start: datetime, end: datetime) -> list[FundingPayment]:
  raise NotImplementedError(
    'not supported: `uta.account.financial_records` filters on a free-text `type` the '
    'venue documents as open-ended without listing its values, so there is no documented '
    'funding-fee value to filter on'
  )

# not executed: not supported, see the note above
{symbol: await funding_payments(symbol, funding_start, funding_end) for symbol in PERP_MARKETS}


# %%
async def perp_position(symbol: str) -> PerpPosition:
  raw = await client.uta.position.current_positions(category=PERP_CATEGORY, symbol=symbol)
  rows = raw['list'] or []
  row = rows[0] if rows else None
  if row is None:
    return PerpPosition()
  total = Decimal(row['total'])
  size = total if row['posSide'] == 'long' else -total
  return PerpPosition(size=size, entry_price=Decimal(row['avgPrice']))

{symbol: await perp_position(symbol) for symbol in PERP_MARKETS}


# %% [markdown]
# `perp_collateral()` reads the *same* unified `account.assets()` call as spot `position()`
# above and as `reporting/uta.ipynb`'s `Snapshots` -- UTA has one collateral pool shared
# across every category, so there's no per-symbol account lookup the way Classic's
# `mix.account.get(symbol=...)` needs. `margin_mode` is read off `account.settings()`'s
# `symbolConfigList`, which holds one row per (symbol, margin mode) rather than one per
# symbol -- BTCUSDT appears twice live here, `crossed` at leverage 20 and `isolated` at
# leverage 10, while ETHUSDT and SOLUSDT have no row at all. The lookup below takes the
# first row matching the symbol and falls back to `'cross'` when there is none, then
# translates Bitget's `'crossed'`/`'isolated'` spelling to the abstract
# `Literal['cross', 'isolated']`.

# %%
async def perp_collateral(symbol: str) -> PerpCollateral:
  assets, settings = await asyncio.gather(
    client.uta.account.assets(), client.uta.account.settings(),
  )
  cfg = next((c for c in settings['symbolConfigList'] if c['symbol'] == symbol), None)
  margin_mode = 'isolated' if cfg and cfg['marginMode'] == 'isolated' else 'cross'
  return PerpCollateral(
    equity=assets['accountEquity'],
    free_collateral=assets['effEquity'],
    initial_margin=assets['imr'],
    maintenance_margin=assets['mmr'],
    leverage=assets['leverage'],
    margin_mode=margin_mode,
  )

{symbol: await perp_collateral(symbol) for symbol in PERP_MARKETS}


# %%
async def perp_available_notional(symbol: str) -> Decimal:
  collateral, rules = await asyncio.gather(perp_collateral(symbol), perp_rules(symbol))
  max_leverage = rules.details.get('maxLeverage') or Decimal(1)
  return collateral.free_collateral * max_leverage

{symbol: await perp_available_notional(symbol) for symbol in PERP_MARKETS}


# %%
async def perp_place_order(symbol: str, order: Order, *, settings: Settings = {}) -> OrderResponse:
  qty_signed = Decimal(str(order['qty']))
  side = 'buy' if qty_signed > 0 else 'sell'
  qty = abs(qty_signed)
  price = Decimal(str(order['price']))
  body: LimitOrderRequest | MarketOrderRequest
  if order['type'] == 'MARKET':
    body = {'category': PERP_CATEGORY, 'symbol': symbol, 'side': side, 'qty': qty, 'orderType': 'market'}
  else:
    time_in_force = 'post_only' if order['type'] == 'POST_ONLY' else 'gtc'
    body = {
      'category': PERP_CATEGORY, 'symbol': symbol, 'side': side, 'qty': qty,
      'orderType': 'limit', 'price': price, 'timeInForce': time_in_force,
    }
  raw = await client.uta.trade.order.place(body)
  return OrderResponse(id=raw['orderId'], details=raw)

# Not executed here -- would place a real order on the account.
await perp_place_order('BTCUSDT', {'qty': Decimal('0.001'), 'price': Decimal('20000'), 'type': 'LIMIT'})


# %%
async def perp_cancel_order(symbol: str, id: str, *, settings: Settings = {}):
  return await client.uta.trade.order.cancel(order_id=id, category=PERP_CATEGORY)

# Not executed here -- would cancel a real order on the account.
await perp_cancel_order('BTCUSDT', '123456')

# %% [markdown]
# ### Coverage assessment: `PerpMarket` (UTA)
#
# **Mostly supported**, and richer than Classic on the collateral side: UTA's
# `account.assets()` directly exposes `imr`/`mmr`/`leverage`/`effEquity`, so
# `perp_collateral()` maps onto venue figures. With no open position on this account all
# four read as `0` except `effEquity` (15.76 against 20.39 of equity), so the mapping is
# demonstrated rather than numerically exercised. `index()` reads `tickers`'s `indexPrice`
# (present for futures categories) and raises rather than falling back to the last price
# if it were missing. `funding_payments` is not supported (see its note above).
#
# `uta.market.funding_rate.current` validates on typed-bitget 0.4.0: `cashDividendNextUpdate`
# admits the literal string `'null'` the venue sends for ordinary (non-Reality) symbols.
