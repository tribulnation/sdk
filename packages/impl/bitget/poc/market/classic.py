# %% [markdown]
# # Bitget `market` -- gap check (Classic)
#
# Bitget's production SDK (`tribulnation.bitget`) has no `Market`/`PerpMarket`/`Exchange`
# implementation -- only `earn`/`wallet`/`reporting`. `typed_bitget` does expose real spot
# and futures (`mix`) trading surfaces though (order book, symbol/contract rules, place/
# cancel order, open orders, fills, positions, funding), confirmed by independently reading
# `classic/spot/{orderbook,symbols,order,account}` and `classic/mix/{market,order,position,
# account}`. This notebook hand-maps that surface onto `Market` (spot) and `PerpMarket`
# (mix USDT-FUTURES), the same way `earn`/`wallet`/`reporting` do above.
#
# Split by account mode for the same reason as the other three pillars: Classic keeps spot
# and futures balances in genuinely separate compartments (`spot.account.assets` vs.
# `mix.account.get`, each with its own `available`/margin semantics), so a Classic-mode
# integration's `position()`/`collateral()`/`available_notional()` are inherently
# mode-specific -- not a case where market data happens to be identical across modes.

# %%
import asyncio
import os
from decimal import Decimal
from datetime import datetime, timedelta, timezone

from typing_extensions import Literal

from typed_bitget import Bitget
from typed_bitget.classic.spot.order.place import SpotLimitOrderRequest, SpotMarketOrderRequest
from typed_bitget.classic.mix.order.place import MixLimitOrderRequest, MixMarketOrderRequest
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
  access_key=os.environ['BITGET_CLASSIC_ACCESS_KEY'],
  secret_key=os.environ['BITGET_CLASSIC_SECRET_KEY'],
  passphrase=os.environ['BITGET_CLASSIC_PASSPHRASE'],
).__aenter__()

SPOT_MARKETS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']
PERP_MARKETS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']
PRODUCT_TYPE = 'USDT-FUTURES'


# %% [markdown]
# ## `Market` (spot)

# %%
async def depth(symbol: str, *, levels: int | None = None) -> Book:
  raw = await client.classic.spot.orderbook(symbol=symbol, limit=levels)
  return Book(
    bids=[Book.Entry(price, qty) for price, qty in raw['bids']],
    asks=[Book.Entry(price, qty) for price, qty in raw['asks']],
  )

{symbol: await depth(symbol, levels=5) for symbol in SPOT_MARKETS}


# %%
async def rules(symbol: str, *, refetch: bool = False) -> Rules:
  raw = await client.classic.spot.symbols(symbol=symbol)
  sym = raw[0]
  return Rules(
    base=sym['baseCoin'],
    quote=sym['quoteCoin'],
    fee_asset=sym['quoteCoin'],
    tick_size=Decimal(10) ** -int(sym['pricePrecision']),
    step_size=Decimal(10) ** -int(sym['quantityPrecision']),
    fixed_min_qty=sym['minTradeAmount'] or None,
    min_value=sym['minTradeUSDT'],
    max_qty=sym['maxTradeAmount'],
    maker_fee=sym['makerFeeRate'],
    taker_fee=sym['takerFeeRate'],
    api=sym['status'] == 'online',
    details=sym,
  )

{symbol: await rules(symbol) for symbol in SPOT_MARKETS}


# %%
async def open_orders(symbol: str) -> list[OrderState]:
  raw = await client.classic.spot.order.open(symbol=symbol)
  out: list[OrderState] = []
  for o in raw:
    size = Decimal(o['size'])
    filled = Decimal(o['baseVolume'])
    sign = 1 if o['side'] == 'buy' else -1
    out.append(OrderState(
      id=o['orderId'],
      price=Decimal(o['basePrice']),
      qty=sign * size,
      filled_qty=sign * filled,
      active=True,  # this endpoint only lists currently-open orders
      details=o,
    ))
  return out

{symbol: await open_orders(symbol) for symbol in SPOT_MARKETS}


# %%
async def trades_history(symbol: str, start: datetime, end: datetime) -> list[Trade]:
  raw = await client.classic.spot.order.fills(symbol=symbol, start_time=start, end_time=end)
  out: list[Trade] = []
  for f in raw:
    size = Decimal(f['size'])
    fee_detail = f['feeDetail']
    fee_amount = abs(Decimal(fee_detail['totalFee']))
    out.append(Trade(
      id=f['tradeId'],
      price=Decimal(f['priceAvg']),
      qty=size if f['side'] == 'buy' else -size,
      time=f['cTime'],
      maker=f['tradeScope'] == 'maker',
      fee=Trade.Fee(amount=fee_amount, asset=fee_detail['feeCoin']) if fee_amount else None,
      details=f,
    ))
  return out

end = datetime.now(timezone.utc)
start = end - timedelta(hours=24)
{symbol: await trades_history(symbol, start, end) for symbol in SPOT_MARKETS}


# %%
async def spot_asset(coin: str):
  raw = await client.classic.spot.account.assets(coin=coin)
  return raw[0] if raw else None


async def position(symbol: str) -> Position:
  base = symbol.removesuffix('USDT')  # SPOT_MARKETS are all *USDT pairs here
  balance = await spot_asset(base)
  size = (
    Decimal(balance['available']) + Decimal(balance['frozen']) + Decimal(balance['locked'])
    if balance else Decimal(0)
  )
  return Position(size=size)

{symbol: await position(symbol) for symbol in SPOT_MARKETS}


# %%
async def available_notional(symbol: str) -> Decimal:
  balance = await spot_asset('USDT')
  return Decimal(balance['available']) if balance else Decimal(0)

{symbol: await available_notional(symbol) for symbol in SPOT_MARKETS}


# %%
async def place_order(symbol: str, order: Order, *, settings: Settings = {}) -> OrderResponse:
  qty = Decimal(str(order['qty']))
  side = 'buy' if qty > 0 else 'sell'
  size = abs(qty)
  price = Decimal(str(order['price']))
  body: SpotLimitOrderRequest | SpotMarketOrderRequest
  if order['type'] == 'MARKET':
    body = {'symbol': symbol, 'side': side, 'orderType': 'market', 'force': 'gtc', 'size': size}
  elif order['type'] == 'POST_ONLY':
    body = {'symbol': symbol, 'side': side, 'orderType': 'limit', 'force': 'post_only', 'price': price, 'size': size}
  else:
    body = {'symbol': symbol, 'side': side, 'orderType': 'limit', 'force': 'gtc', 'price': price, 'size': size}
  raw = await client.classic.spot.order.place(body)
  return OrderResponse(id=raw['orderId'], details=raw)

# Not executed here -- would place a real order on the account.
await place_order('BTCUSDT', {'qty': Decimal('0.0001'), 'price': Decimal('20000'), 'type': 'LIMIT'})


# %%
async def cancel_order(symbol: str, id: str, *, settings: Settings = {}):
  return await client.classic.spot.order.cancel(symbol=symbol, order_id=id)

# Not executed here -- would cancel a real order on the account.
await cancel_order('BTCUSDT', '123456')

# %% [markdown]
# ### Coverage assessment: `Market` (spot)
#
# **Fully supported.** `classic.spot.{orderbook,symbols,order,account}` cover every
# abstract method live-tested above with real market data. The account holds only dust
# (BTC, ETH, USDT, USDC, AVAX, all well under a dollar) and has no open spot orders or
# fills in the last 24 hours, so `open_orders`/`trades_history` come back empty and
# `position()` returns those dust balances. `Rules`'s `tick_size`/`step_size` are derived
# from `pricePrecision`/`quantityPrecision` (decimal place *counts*, not tick sizes
# directly) rather than read off a dedicated field, since Bitget doesn't expose one.
# `collateral()` is left unimplemented (matches the abstract base class's own default
# `NotImplementedError` -- there's no separate "collateral bucket" concept for a spot
# balance beyond the balance itself, same choice Binance's `poc/market.ipynb` makes for
# its spot section).
#
# `spot.account.assets` validates for a coin the account holds nothing in: SOL sends
# `limitAvailable: null`, which the declaration (`Decimal | None`) admits.

# %% [markdown]
# ## `PerpMarket` (Classic Mix, USDT-FUTURES)

# %%
# `classic.mix.market.orderbook`'s `limit` is a fixed enum (`'1' | '5' | '15' | '50' | 'max'`),
# unlike `classic.spot.orderbook`'s arbitrary `int` -- `levels` is restricted to the four
# numeric members and mapped here.
_DEPTH_LEVELS: dict[int, Literal['1', '5', '15', '50']] = {1: '1', 5: '5', 15: '15', 50: '50'}


async def perp_depth(symbol: str, *, levels: Literal[1, 5, 15, 50] | None = None) -> Book:
  raw = await client.classic.mix.market.orderbook(
    symbol=symbol, product_type=PRODUCT_TYPE,
    limit=_DEPTH_LEVELS[levels] if levels is not None else None,
  )
  return Book(
    bids=[Book.Entry(Decimal(str(p)), Decimal(str(q))) for p, q in raw['bids']],
    asks=[Book.Entry(Decimal(str(p)), Decimal(str(q))) for p, q in raw['asks']],
  )

{symbol: await perp_depth(symbol, levels=5) for symbol in PERP_MARKETS}


# %%
async def perp_rules(symbol: str, *, refetch: bool = False) -> Rules:
  raw = await client.classic.mix.market.contracts(product_type=PRODUCT_TYPE, symbol=symbol)
  c = raw[0]
  return Rules(
    base=c['baseCoin'],
    quote=c['quoteCoin'],
    fee_asset=c['quoteCoin'],
    tick_size=Decimal(10) ** -int(c['pricePlace']),
    step_size=c['sizeMultiplier'],
    fixed_min_qty=c['minTradeNum'],
    min_value=c['minTradeUSDT'],
    max_qty=Decimal(c['maxOrderQty']),
    maker_fee=c['makerFeeRate'],
    taker_fee=c['takerFeeRate'],
    api=c['symbolStatus'] == 'normal',
    details=c,
  )

{symbol: await perp_rules(symbol) for symbol in PERP_MARKETS}


# %%
async def perp_open_orders(symbol: str) -> list[OrderState]:
  raw = await client.classic.mix.order.open(product_type=PRODUCT_TYPE, symbol=symbol)
  out: list[OrderState] = []
  for o in raw['entrustedList'] or []:
    size = Decimal(o['size'])
    filled = Decimal(o['baseVolume'])
    sign = 1 if o['side'] == 'buy' else -1
    out.append(OrderState(
      id=o['orderId'],
      price=Decimal(o['price']),
      qty=sign * size,
      filled_qty=sign * filled,
      active=o['status'] in ('live', 'partially_filled'),
      details=o,
    ))
  return out

{symbol: await perp_open_orders(symbol) for symbol in PERP_MARKETS}


# %%
async def perp_trades_history(symbol: str, start: datetime, end: datetime) -> list[Trade]:
  raw = await client.classic.mix.order.fills(
    product_type=PRODUCT_TYPE, symbol=symbol, start_time=start, end_time=end,
  )
  out: list[Trade] = []
  for f in raw['fillList'] or []:
    fee_amount = sum((abs(Decimal(d['totalFee'])) for d in f['feeDetail']), Decimal(0))
    fee_asset = f['feeDetail'][0]['feeCoin'] if f['feeDetail'] else None
    size = Decimal(f['baseVolume'])
    out.append(Trade(
      id=f['tradeId'],
      price=Decimal(f['price']),
      qty=size if f['side'] == 'buy' else -size,
      time=f['cTime'],
      maker=f['tradeScope'] == 'maker',
      fee=Trade.Fee(amount=fee_amount, asset=fee_asset) if fee_amount and fee_asset else None,
      details=f,
    ))
  return out

{symbol: await perp_trades_history(symbol, start, end) for symbol in PERP_MARKETS}


# %%
async def index(symbol: str, *, settings: Settings = {}) -> Decimal:
  raw = await client.classic.mix.market.symbol_price(symbol, product_type=PRODUCT_TYPE)
  return raw[0]['indexPrice']

{symbol: await index(symbol) for symbol in PERP_MARKETS}


# %%
async def next_funding(symbol: str) -> NextFunding:
  rate, time_info = await asyncio.gather(
    client.classic.mix.market.funding.current_rate(symbol=symbol, product_type=PRODUCT_TYPE),
    client.classic.mix.market.funding.time(symbol=symbol, product_type=PRODUCT_TYPE),
  )
  return NextFunding(
    rate=rate[0]['fundingRate'],
    time=time_info[0]['nextFundingTime'],
    interval=timedelta(hours=int(rate[0]['fundingRateInterval'])),
  )

{symbol: await next_funding(symbol) for symbol in PERP_MARKETS}


# %%
async def funding_rates(
  symbol: str, start: datetime | None = None, end: datetime | None = None,
) -> list[FundingRate]:
  # `rate_history` paginates by page number, not a date range -- filtered client-side.
  raw = await client.classic.mix.market.funding.rate_history(
    symbol=symbol, product_type=PRODUCT_TYPE, page_size=50,
  )
  out = [FundingRate(rate=r['fundingRate'], time=r['fundingTime']) for r in raw]
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
# Bitget has no dedicated funding-fee endpoint under `classic.mix`. Both ledgers that would
# carry the payments filter on a free-text type field the venue publishes no closed set
# for: `classic.mix.account.bills`'s `businessType` and `classic.tax.futures_records`'s
# `futureTaxType` (the venue documents that 30+ values exist without listing them). Walking
# eight months of this account's `USDT-FUTURES` tax records turned up 15 distinct values
# (`buy_deal`, `sell_deal`, `open_long`, `open_short`, `close_short`, `burst_close_long`,
# `adjust_margin_ifm`, `contract_margin_settle_fee`, `trans_to_cross`, `trans_to_isolated`,
# `trans_to_exchange`, `trans_from_exchange`, `user_grants_issue`, `user_grants_recycle`,
# `risk_captital_user_transfer`), none documented as the funding settlement, and this
# account has never held a position across a settlement to observe one. Rather than guess a
# substring filter, the method raises.

# %%
async def funding_payments(symbol: str, start: datetime, end: datetime) -> list[FundingPayment]:
  raise NotImplementedError(
    'not supported: Bitget publishes no closed set of futures ledger types '
    '(`classic.mix.account.bills` `businessType`, `classic.tax.futures_records` '
    '`futureTaxType`), so there is no documented funding-fee value to filter on'
  )

# not executed: not supported, see the note above
{symbol: await funding_payments(symbol, funding_start, funding_end) for symbol in PERP_MARKETS}


# %%
async def perp_position(symbol: str) -> PerpPosition:
  raw = await client.classic.mix.position.get(product_type=PRODUCT_TYPE, symbol=symbol, margin_coin='USDT')
  row = raw[0] if raw else None
  if row is None:
    return PerpPosition()
  size = row['total'] if row['holdSide'] == 'long' else -row['total']
  return PerpPosition(size=size, entry_price=row['openPriceAvg'])

{symbol: await perp_position(symbol) for symbol in PERP_MARKETS}


# %%
async def perp_collateral(symbol: str) -> PerpCollateral:
  raise NotImplementedError(
    'not supported: `MixAccountAsset` carries no initial/maintenance margin figure '
    '(only `available`, `accountEquity` and `crossedRiskRate`), and `PerpCollateral` '
    'requires both'
  )

# not executed: not supported, see the coverage note below
{symbol: await perp_collateral(symbol) for symbol in PERP_MARKETS}


# %%
async def perp_account(symbol: str):
  return await client.classic.mix.account.get(
    symbol=symbol, product_type=PRODUCT_TYPE, margin_coin='USDT',
  )


async def perp_available_notional(symbol: str) -> Decimal:
  account, rules = await asyncio.gather(perp_account(symbol), perp_rules(symbol))
  return account['available'] * rules.details['maxLever']

{symbol: await perp_available_notional(symbol) for symbol in PERP_MARKETS}


# %%
async def perp_place_order(symbol: str, order: Order, *, settings: Settings = {}) -> OrderResponse:
  qty = Decimal(str(order['qty']))
  side = 'buy' if qty > 0 else 'sell'
  size = abs(qty)
  price = Decimal(str(order['price']))
  body: MixLimitOrderRequest | MixMarketOrderRequest
  if order['type'] == 'MARKET':
    body = {
      'symbol': symbol, 'productType': PRODUCT_TYPE, 'marginMode': 'crossed', 'marginCoin': 'USDT',
      'side': side, 'orderType': 'market', 'size': size,
    }
  else:
    force = 'post_only' if order['type'] == 'POST_ONLY' else 'gtc'
    body = {
      'symbol': symbol, 'productType': PRODUCT_TYPE, 'marginMode': 'crossed', 'marginCoin': 'USDT',
      'side': side, 'orderType': 'limit', 'force': force, 'price': price, 'size': size,
    }
  raw = await client.classic.mix.order.place(body)
  return OrderResponse(id=raw['orderId'], details=raw)

# Not executed here -- would place a real order on the account.
await perp_place_order('BTCUSDT', {'qty': Decimal('0.001'), 'price': Decimal('20000'), 'type': 'LIMIT'})


# %%
async def perp_cancel_order(symbol: str, id: str, *, settings: Settings = {}):
  return await client.classic.mix.order.cancel(symbol=symbol, product_type=PRODUCT_TYPE, order_id=id)

# Not executed here -- would cancel a real order on the account.
await perp_cancel_order('BTCUSDT', '123456')

# %% [markdown]
# ### Coverage assessment: `PerpMarket` (Classic Mix)
#
# **Mostly supported.** `depth`, `rules`, `open_orders`, `trades_history`, `index`,
# `next_funding`, `funding_rates`, `perp_position` and `available_notional` map onto
# dedicated endpoints and are confirmed against live (mostly empty) responses: `index()`
# reads `classic.mix.market.symbol_price`'s `indexPrice`, and `available_notional` is the
# account's `available` margin times the contract's `maxLever`.
#
# Two methods are not supported on Classic. `perp_collateral` has nothing to fill
# `PerpCollateral.initial_margin`/`maintenance_margin` from: `MixAccountAsset` exposes
# `available`, `accountEquity` and `crossedRiskRate` but no account-level margin
# requirement (UTA's `account.assets` does, see `market/uta.ipynb`). `funding_payments`
# has no documented ledger type to filter on (see its note above).
#
# `mix.position.list` returns no open positions for any product type and the USDT-FUTURES
# equity is 0.0042 USDT, so the account-scoped mappings are demonstrated, not numerically
# exercised. `classic.mix.order.fills` and `classic.mix.account.get` validate on this
# one-way, mixed-margin-mode account (`tradeSide` admits `buy_single`/`sell_single`; the
# `*UnrealizedPL` fields admit `''`). `classic.mix.order.open`'s `tradeSide` still uses the
# narrow `MixTradeSide` alias, so `open_orders` validates only because there are no open
# orders -- tracked in `typed-client-issues.md`.
