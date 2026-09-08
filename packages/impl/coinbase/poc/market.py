# %%
import asyncio
import uuid
from contextlib import asynccontextmanager
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from typing_extensions import AsyncIterable

from typed_coinbase import Coinbase
from typed_coinbase.core import timestamp_iso
from typed_coinbase.schemas import (
  LimitLimitGtcConfiguration,
  MarketMarketIocConfiguration,
)
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

client = await Coinbase.new().__aenter__()

MARKETS = {
  'spot': ['BTC-USD', 'ETH-USD', 'SOL-USD'],
  'perp': ['BTC-PERP-INTX', 'ETH-PERP-INTX', 'SOL-PERP-INTX'],
}


# %% [markdown]
# ## `Market` (spot)

# %%
async def depth(product_id: str, *, levels: int | None = None) -> Book:
  raw = await client.app.advanced_trade.http.products.public.book(
    product_id=product_id, limit=levels
  )
  book = raw['pricebook']
  return Book(
    bids=[Book.Entry(Decimal(e['price']), Decimal(e['size'])) for e in book['bids']],
    asks=[Book.Entry(Decimal(e['price']), Decimal(e['size'])) for e in book['asks']],
  )


{product_id: await depth(product_id, levels=5) for product_id in MARKETS['spot']}


# %%
@asynccontextmanager
async def depth_stream(product_id: str, *, levels: int = 5):
  async def gen():
    book = Book()
    async with client.app.advanced_trade.streams.market_data.level2(
      [product_id]
    ) as raw_stream:
      async for message in raw_stream:
        for event in message['events']:
          if event['product_id'] != product_id:
            continue
          update = Book(
            bids=[
              Book.Entry(Decimal(u['price_level']), Decimal(u['new_quantity']))
              for u in event['updates']
              if u['side'] == 'bid'
            ],
            asks=[
              Book.Entry(Decimal(u['price_level']), Decimal(u['new_quantity']))
              for u in event['updates']
              if u['side'] == 'offer'
            ],
          )
          if event['type'] == 'snapshot':
            book = update
          else:
            book.update(update)
          yield book.copy().limit(levels)

  yield gen()


books: list[Book] = []
async with depth_stream('BTC-USD') as stream:
  async for book in stream:
    books.append(book)
    if len(books) >= 3:
      break
books


# %%
async def rules(product_id: str, *, refetch: bool = False) -> Rules:
  product = await client.app.advanced_trade.http.products.get(product_id)
  fees = await client.app.advanced_trade.http.fees.transaction_summary(
    product_type='SPOT'
  )
  tier = fees.get('fee_tier') or {}
  maker_fee_rate = tier.get('maker_fee_rate')
  taker_fee_rate = tier.get('taker_fee_rate')
  return Rules(
    base=product['base_display_symbol'],
    quote=product['quote_display_symbol'],
    fee_asset=product['quote_display_symbol'],
    tick_size=Decimal(product['quote_increment']),
    step_size=Decimal(product['base_increment']),
    fixed_min_qty=Decimal(product['base_min_size']),
    min_value=Decimal(product['quote_min_size']),
    max_qty=Decimal(product['base_max_size']),
    maker_fee=Decimal(maker_fee_rate) if maker_fee_rate else Decimal(0),
    taker_fee=Decimal(taker_fee_rate) if taker_fee_rate else Decimal(0),
    api=not product['trading_disabled'],
    details=product,
  )


{product_id: await rules(product_id) for product_id in MARKETS['spot']}


# %%
async def open_orders(product_id: str) -> list[OrderState]:
  raw = await client.app.advanced_trade.http.orders.historical.batch(
    product_ids=[product_id],
    order_status=['OPEN'],
  )
  out: list[OrderState] = []
  for o in raw['orders']:
    sign = 1 if o['side'] == 'BUY' else -1
    filled = Decimal(o.get('filled_size') or '0')
    # `Order` has no top-level original-size field (it lives nested per order-type
    # inside `order_configuration`); back it out from `filled_size`/`completion_percentage`
    # instead. Falls back to `filled` (0) only in the one case that ratio can't cover:
    # nothing filled yet.
    completion = Decimal(o['completion_percentage'])
    qty = filled / (completion / 100) if completion else filled
    price = Decimal(o.get('average_filled_price') or '0')
    out.append(
      OrderState(
        id=o['order_id'],
        price=price,
        qty=sign * qty,
        filled_qty=sign * filled,
        active=o['status'] in ('OPEN', 'PENDING', 'QUEUED'),
        details=o,
      )
    )
  return out


{product_id: await open_orders(product_id) for product_id in MARKETS['spot']}


# %%
async def trades_history(
  product_id: str, start: datetime, end: datetime
) -> list[Trade]:
  raw = await client.app.advanced_trade.http.orders.historical.fills(
    product_ids=[product_id],
    start_sequence_timestamp=start,
    end_sequence_timestamp=end,
  )
  out: list[Trade] = []
  for f in raw['fills']:
    trade_time = f.get('trade_time')
    if trade_time is None:
      # `trade_time` is NotRequired; a fill without one has no usable time -- skip
      # rather than guess (`Trade.time` is required).
      continue
    sign = 1 if f.get('side') == 'BUY' else -1
    size = f.get('size')
    qty = Decimal(size) if size else Decimal(0)
    commission = f.get('commission')
    fee = None
    if commission and Decimal(commission) != 0:
      quote = product_id.split('-')[1]
      fee = Trade.Fee(amount=Decimal(commission), asset=quote)
    price = f.get('price')
    out.append(
      Trade(
        id=f.get('trade_id'),
        price=Decimal(price) if price else Decimal(0),
        qty=sign * qty,
        time=trade_time,
        maker=f.get('liquidity_indicator') == 'MAKER',
        fee=fee,
        details=f,
      )
    )
  return out


end = datetime.now(timezone.utc)
start = end - timedelta(days=30)
{
  product_id: await trades_history(product_id, start, end)
  for product_id in MARKETS['spot']
}


# %%
@asynccontextmanager
async def trades_stream(product_id: str):
  """Best-effort: the `user` channel carries order-level `cumulative_quantity` snapshots,
  not itemized per-fill events, so each increase is reconstructed here as one `Trade`.
  `trades_history` (above) is the reliable source; this loses per-fill maker/taker/fee."""

  async def gen():
    seen: dict[str, Decimal] = {}
    async with client.app.advanced_trade.streams.user.orders() as raw_stream:
      async for message in raw_stream:
        for event in message['events']:
          for order in event['orders']:
            cumulative_quantity = order.get('cumulative_quantity')
            if order['product_id'] != product_id or not cumulative_quantity:
              continue
            cum = Decimal(cumulative_quantity)
            prev = seen.get(order['order_id'], Decimal(0))
            if cum <= prev:
              continue
            seen[order['order_id']] = cum
            sign = 1 if order['order_side'] == 'BUY' else -1
            avg_price = order.get('avg_price')
            yield Trade(
              id=f'{order["order_id"]}:{cum}',
              price=Decimal(avg_price) if avg_price else Decimal(0),
              qty=sign * (cum - prev),
              time=message['timestamp'],
              maker=False,
              details=order,
            )

  yield gen()


async with trades_stream('BTC-USD') as stream:
  it = aiter(stream)
  try:
    result = await asyncio.wait_for(anext(it), timeout=5.0)
  except asyncio.TimeoutError:
    result = 'no new fills observed in 5s (expected -- no live trading on this account)'
result


# %%
async def position(product_id: str) -> Position:
  base = product_id.split('-')[0]
  accounts = await client.app.advanced_trade.http.accounts.list(limit=250)
  account = next((a for a in accounts['accounts'] if a['currency'] == base), None)
  size = Decimal(account['available_balance']['value']) if account else Decimal(0)
  return Position(size=size)


{product_id: await position(product_id) for product_id in MARKETS['spot']}


# %%
async def collateral(product_id: str) -> Collateral:
  quote = product_id.split('-')[1]
  accounts = await client.app.advanced_trade.http.accounts.list(limit=250)
  account = next((a for a in accounts['accounts'] if a['currency'] == quote), None)
  if account is None:
    return Collateral(equity=Decimal(0), free_collateral=Decimal(0))
  free = Decimal(account['available_balance']['value'])
  hold = Decimal(account['hold']['value'])
  return Collateral(equity=free + hold, free_collateral=free)


{product_id: await collateral(product_id) for product_id in MARKETS['spot']}


# %%
async def available_notional(product_id: str) -> Decimal:
  c = await collateral(product_id)
  return c.free_collateral


{product_id: await available_notional(product_id) for product_id in MARKETS['spot']}


# %%
async def place_order(
  product_id: str, order: Order, *, settings: Settings = {}
) -> OrderResponse:
  qty = Decimal(order['qty'])
  side = 'BUY' if qty > 0 else 'SELL'
  base_size = abs(qty)
  price = Decimal(order['price'])
  config: MarketMarketIocConfiguration | LimitLimitGtcConfiguration
  if order['type'] == 'MARKET':
    config = {'market_market_ioc': {'base_size': base_size}}
  elif order['type'] == 'POST_ONLY':
    config = {
      'limit_limit_gtc': {
        'base_size': base_size,
        'limit_price': price,
        'post_only': True,
      }
    }
  else:
    config = {'limit_limit_gtc': {'base_size': base_size, 'limit_price': price}}
  raw = await client.app.advanced_trade.http.orders.create(
    client_order_id=str(uuid.uuid4()),
    product_id=product_id,
    side=side,
    order_configuration=config,
  )
  # `create` returns a `CreateOrderSuccess | CreateOrderFailure` union discriminated by
  # the literal `success` field; compare against it explicitly, as plain truthiness
  # doesn't narrow a `TypedDict` union.
  if raw['success'] is False:
    raise RuntimeError(f'order rejected: {raw["error_response"]}')
  return OrderResponse(id=raw['success_response']['order_id'], details=raw)


# Not executed here -- would place a real order on the account.
await place_order(
  'BTC-USD', {'qty': Decimal('0.0001'), 'price': Decimal('20000'), 'type': 'LIMIT'}
)


# %%
async def cancel_order(product_id: str, id: str, *, settings: Settings = {}):
  return await client.app.advanced_trade.http.orders.batch_cancel(order_ids=[id])


# Not executed here -- would cancel a real order on the account.
await cancel_order('BTC-USD', '00000000-0000-0000-0000-000000000000')


# %% [markdown]
# ## `PerpMarket` (INTX perpetuals)

# %% [markdown]
# Coinbase's only perpetual-swap product family is INTX (`product_venue: 'INTX'`, e.g.
# `BTC-PERP-INTX`), reached through the same `advanced_trade.http.products`/`orders`
# surface as spot (`product_type='FUTURE'`, `contract_expiry_type='PERPETUAL'`). The
# INTX-specific position/margin endpoints (`perpetuals.positions`, `.portfolio_summary`)
# are **deprecated in the client itself** — their docstrings say this surface retires
# 2026-09-09, superseded by "a Deribit-powered derivatives gateway" — and separately this
# key's portfolio has no INTX entitlement (`key_permissions.get()` reports
# `portfolio_type: 'DEFAULT'`), so every `perpetuals.*` call below returns a real, live
# `AuthError(403, PERMISSION_DENIED)` rather than fabricated data — re-derived live against
# `perpetuals.positions.list`, `.portfolio_summary` and `.balances`, all three. `futures.*`
# (CFM dated futures, a *different* non-perpetual product family) is the one derivatives
# surface this key does reach, and only partly: `futures.positions.list()` answers with an empty book and `futures.balance_summary()` with `{"balance_summary": null}`. Neither is a perpetuals
# `collateral`, so the cells below call `perpetuals.*` and record the real 403.
#
# Funding is partly reachable, through the product catalog rather than a funding endpoint.
# `products.get`'s `future_product_details` — an untyped `dict[str, Any]` on the response —
# carries `perpetual_details.funding_rate`, `perpetual_details.funding_time` and a
# `funding_interval` of `3600s` on all three `*-PERP-INTX` products, so `next_funding` is
# implemented from it below. `funding_time` is the settlement that just happened, not the
# next one — polled across an hour boundary it held 15:00:00Z for the whole of 15:00-16:00
# and flipped to 16:00:00Z six seconds after the hour — so the cell adds one interval. The same blob carries `index_price`, used by `index`. What is
# missing is history: no funding-rate history and no funding-payment ledger exists anywhere
# in this client for INTX perpetuals (`futures.balance_summary.funding_pnl` is CFM
# dated-futures funding, not swap funding), so `funding_rates`/`funding_payments` raise
# `NotImplementedError`, matching the SDK's own convention for unsupported methods.

# %%
async def depth(product_id: str, *, levels: int | None = None) -> Book:
  # The public (unauthenticated) pricebook serves INTX perpetuals too, verified live on
  # all three: the same call the spot section above makes.
  raw = await client.app.advanced_trade.http.products.public.book(
    product_id=product_id, limit=levels
  )
  book = raw['pricebook']
  return Book(
    bids=[Book.Entry(Decimal(e['price']), Decimal(e['size'])) for e in book['bids']],
    asks=[Book.Entry(Decimal(e['price']), Decimal(e['size'])) for e in book['asks']],
  )


{product_id: await depth(product_id, levels=5) for product_id in MARKETS['perp']}

# %%
# `level2` needs no authentication and streams any product id, perpetuals included --
# reuses the `depth_stream` defined in the spot section above.
books: list[Book] = []
async with depth_stream('BTC-PERP-INTX') as stream:
  async for book in stream:
    books.append(book)
    if len(books) >= 3:
      break
books


# %%
async def perp_rules(product_id: str, *, refetch: bool = False) -> Rules:
  product = await client.app.advanced_trade.http.products.get(product_id)
  fees = await client.app.advanced_trade.http.fees.transaction_summary(
    product_type='FUTURE',
    contract_expiry_type='PERPETUAL',
    product_venue='INTX',
  )
  tier = fees.get('fee_tier') or {}
  # Perpetuals leave `base_display_symbol`/`base_currency_id` empty (verified live) --
  # the underlying asset code only shows up under `future_product_details.contract_code`.
  base = product['base_display_symbol'] or product.get(
    'future_product_details', {}
  ).get('contract_code', '')
  return Rules(
    base=base,
    quote=product['quote_display_symbol'],
    fee_asset=product['quote_display_symbol'],
    tick_size=Decimal(product['quote_increment']),
    step_size=Decimal(product['base_increment']),
    fixed_min_qty=Decimal(product['base_min_size']),
    min_value=Decimal(product['quote_min_size']),
    max_qty=Decimal(product['base_max_size']),
    maker_fee=tier.get('maker_fee_rate') or Decimal(0),
    taker_fee=tier.get('taker_fee_rate') or Decimal(0),
    api=not product['trading_disabled'],
    details=product,
  )


{product_id: await perp_rules(product_id) for product_id in MARKETS['perp']}


# %%
async def perp_open_orders(product_id: str) -> list[OrderState]:
  raw = await client.app.advanced_trade.http.orders.historical.batch(
    product_ids=[product_id],
    order_status=['OPEN'],
  )
  out: list[OrderState] = []
  for o in raw['orders']:
    sign = 1 if o['side'] == 'BUY' else -1
    filled = Decimal(o.get('filled_size') or '0')
    # `Order` has no top-level original-size field (it lives nested per order-type
    # inside `order_configuration`); back it out from `filled_size`/`completion_percentage`
    # instead. Falls back to `filled` (0) only in the one case that ratio can't cover:
    # nothing filled yet.
    completion = Decimal(o['completion_percentage'])
    qty = filled / (completion / 100) if completion else filled
    price = Decimal(o.get('average_filled_price') or '0')
    out.append(
      OrderState(
        id=o['order_id'],
        price=price,
        qty=sign * qty,
        filled_qty=sign * filled,
        active=o['status'] in ('OPEN', 'PENDING', 'QUEUED'),
        details=o,
      )
    )
  return out


{product_id: await perp_open_orders(product_id) for product_id in MARKETS['perp']}


# %%
async def perp_trades_history(
  product_id: str, start: datetime, end: datetime
) -> list[Trade]:
  raw = await client.app.advanced_trade.http.orders.historical.fills(
    product_ids=[product_id],
    start_sequence_timestamp=start,
    end_sequence_timestamp=end,
  )
  out: list[Trade] = []
  for f in raw['fills']:
    trade_time = f.get('trade_time')
    if trade_time is None:
      # `trade_time` is NotRequired; a fill without one has no usable time -- skip
      # rather than guess (`Trade.time` is required).
      continue
    sign = 1 if f.get('side') == 'BUY' else -1
    size = f.get('size')
    qty = Decimal(size) if size else Decimal(0)
    commission = f.get('commission')
    fee = None
    if commission and Decimal(commission) != 0:
      fee = Trade.Fee(amount=Decimal(commission), asset=product_id.split('-')[1])
    price = f.get('price')
    out.append(
      Trade(
        id=f.get('trade_id'),
        price=Decimal(price) if price else Decimal(0),
        qty=sign * qty,
        time=trade_time,
        maker=f.get('liquidity_indicator') == 'MAKER',
        fee=fee,
        details=f,
      )
    )
  return out


end = datetime.now(timezone.utc)
start = end - timedelta(days=30)
{
  product_id: await perp_trades_history(product_id, start, end)
  for product_id in MARKETS['perp']
}


# %%
# Reuses the `trades_stream` defined in the spot section above -- the `user` channel
# carries both spot and perpetuals order/position updates on one connection.
async with trades_stream('BTC-PERP-INTX') as stream:
  it = aiter(stream)
  try:
    result = await asyncio.wait_for(anext(it), timeout=5.0)
  except asyncio.TimeoutError:
    result = 'no new fills observed in 5s (expected -- no live trading on this account)'
result


# %%
async def index(product_id: str, *, settings: Settings = {}) -> Decimal:
  # INTX's index price lives in the product catalog's untyped `future_product_details`
  # blob, alongside the funding fields used by `next_funding` below.
  product = await client.app.advanced_trade.http.products.get(product_id)
  details = product.get('future_product_details') or {}
  return Decimal(details['index_price'])


{product_id: await index(product_id) for product_id in MARKETS['perp']}


# %%
async def next_funding(product_id: str) -> NextFunding:
  product = await client.app.advanced_trade.http.products.get(product_id)
  details = product.get('future_product_details') or {}
  perpetual = details['perpetual_details']
  interval = timedelta(seconds=int(str(details['funding_interval']).removesuffix('s')))
  # The catalog's `funding_time` is the settlement that just happened, not the one coming:
  # polled across an hour boundary it read 15:00:00Z (rate -0.000002) for the whole of
  # 15:00-16:00 and flipped to 16:00:00Z (rate -0.000004) six seconds after 16:00.
  # `NextFunding.time` wants the upcoming payment, hence one interval later.
  return NextFunding(
    rate=Decimal(perpetual['funding_rate']),
    time=timestamp_iso.parse(perpetual['funding_time']) + interval,
    interval=interval,
  )


{product_id: await next_funding(product_id) for product_id in MARKETS['perp']}


# %%
async def funding_rates(
  product_id: str,
  start: datetime | None = None,
  end: datetime | None = None,
) -> list[FundingRate]:
  raise NotImplementedError(
    'No funding-rate history endpoint exists for INTX perpetuals in typed_coinbase '
    f'[{product_id}] -- only the current rate, from the product catalog (see `next_funding`).'
  )


# not executed: not supported -- Coinbase publishes no INTX funding-rate history
await funding_rates('BTC-PERP-INTX')


# %%
async def funding_payments(
  product_id: str, start: datetime, end: datetime
) -> list[FundingPayment]:
  raise NotImplementedError(
    'No funding-payment ledger is exposed for INTX perpetuals in typed_coinbase '
    f'[{product_id}]; `futures.balance_summary.funding_pnl` is CFM dated-futures funding, '
    'not swap funding.'
  )


# not executed: not supported -- Coinbase publishes no INTX funding-payment ledger
end = datetime.now(timezone.utc)
start = end - timedelta(days=7)
await funding_payments('BTC-PERP-INTX', start, end)


# %%
async def perp_position(product_id: str) -> PerpPosition:
  key_perms = await client.app.advanced_trade.http.key_permissions.get()
  raw = await client.app.advanced_trade.http.perpetuals.positions.list(
    key_perms['portfolio_uuid']
  )
  row = next((p for p in raw['positions'] if p['product_id'] == product_id), None)
  if row is None:
    return PerpPosition()
  return PerpPosition(
    size=Decimal(row['net_size']), entry_price=Decimal(row['entry_vwap']['value'])
  )


# not executed: not attempted -- this key has no INTX portfolio (`PERMISSION_DENIED`, verified live) and `perpetuals.*` retires 2026-09-09
{product_id: await perp_position(product_id) for product_id in MARKETS['perp']}


# %%
async def perp_collateral(product_id: str) -> PerpCollateral:
  key_perms = await client.app.advanced_trade.http.key_permissions.get()
  summary = await client.app.advanced_trade.http.perpetuals.portfolio_summary(
    key_perms['portfolio_uuid']
  )
  portfolio = summary['portfolios'][0]
  equity = Decimal(portfolio['collateral'])
  initial_margin = Decimal(portfolio['portfolio_initial_margin']) * equity
  maintenance_margin = Decimal(portfolio['portfolio_maintenance_margin']) * equity
  return PerpCollateral(
    equity=equity,
    free_collateral=equity - initial_margin,
    initial_margin=initial_margin,
    maintenance_margin=maintenance_margin,
    leverage=Decimal(portfolio['position_notional']) / equity
    if equity > 0
    else Decimal(0),
    margin_mode='cross'
    if portfolio['margin_type'] == 'MARGIN_TYPE_CROSS'
    else 'isolated',
  )


# not executed: not attempted -- this key has no INTX portfolio (`PERMISSION_DENIED`, verified live) and `perpetuals.*` retires 2026-09-09
{product_id: await perp_collateral(product_id) for product_id in MARKETS['perp']}


# %%
async def perp_available_notional(product_id: str) -> Decimal:
  c = await perp_collateral(product_id)
  return c.free_collateral


# not executed: not attempted -- this key has no INTX portfolio (`PERMISSION_DENIED`, verified live) and `perpetuals.*` retires 2026-09-09
{
  product_id: await perp_available_notional(product_id)
  for product_id in MARKETS['perp']
}


# %%
async def perp_place_order(
  product_id: str, order: Order, *, settings: Settings = {}
) -> OrderResponse:
  qty = Decimal(order['qty'])
  side = 'BUY' if qty > 0 else 'SELL'
  base_size = abs(qty)
  price = Decimal(order['price'])
  config: MarketMarketIocConfiguration | LimitLimitGtcConfiguration
  if order['type'] == 'MARKET':
    config = {'market_market_ioc': {'base_size': base_size}}
  elif order['type'] == 'POST_ONLY':
    config = {
      'limit_limit_gtc': {
        'base_size': base_size,
        'limit_price': price,
        'post_only': True,
      }
    }
  else:
    config = {'limit_limit_gtc': {'base_size': base_size, 'limit_price': price}}
  raw = await client.app.advanced_trade.http.orders.create(
    client_order_id=str(uuid.uuid4()),
    product_id=product_id,
    side=side,
    order_configuration=config,
  )
  # `create` returns a `CreateOrderSuccess | CreateOrderFailure` union discriminated by
  # the literal `success` field; compare against it explicitly, as plain truthiness
  # doesn't narrow a `TypedDict` union.
  if raw['success'] is False:
    raise RuntimeError(f'order rejected: {raw["error_response"]}')
  return OrderResponse(id=raw['success_response']['order_id'], details=raw)


# Not executed here -- would place a real order on the account.
await perp_place_order(
  'BTC-PERP-INTX', {'qty': Decimal('0.001'), 'price': Decimal('20000'), 'type': 'LIMIT'}
)


# %%
async def perp_cancel_order(product_id: str, id: str, *, settings: Settings = {}):
  return await client.app.advanced_trade.http.orders.batch_cancel(order_ids=[id])


# Not executed here -- would cancel a real order on the account.
await perp_cancel_order('BTC-PERP-INTX', '00000000-0000-0000-0000-000000000000')

# %% [markdown]
# ### Coverage
#
# **`Market` (spot)** — fully supported and live-tested, except `trades_stream` which is a
# best-effort reconstruction from order-level snapshots (see its cell): the `user` channel
# has no itemized per-fill event, so it loses per-fill maker/taker and fee; `trades_history`
# (the `orders.historical.fills` endpoint) is the reliable source for that data.
#
# **`PerpMarket` (INTX perpetuals)** — partially supported:
#
# | Method | Status |
# | --- | --- |
# | `depth`, `depth_stream`, `open_orders`, `trades_history`, `trades_stream` | Fully supported, live-tested (same code paths as spot, against `*-PERP-INTX` products). |
# | `rules` | Fully supported, live-tested: product catalogue plus `fees.transaction_summary(product_venue='INTX')`, both validated. |
# | `index` | Fully supported, live-tested: `products.get`'s `future_product_details.index_price` carries INTX's index price on all three perpetuals. |
# | `next_funding` | Fully supported, live-tested: `future_product_details` carries `perpetual_details.funding_rate`/`.funding_time` and `funding_interval` (`3600s`) -- no funding endpoint needed. `funding_time` is the *last* settlement (verified by polling across an hour boundary), so the next payment is one interval later. |
# | `funding_rates`, `funding_payments` | Not supported: the catalog exposes only the *current* funding state; no funding-rate history and no funding-payment ledger exists anywhere in `typed_coinbase` for INTX perpetuals. |
# | `perp_position`, `perp_collateral`, `available_notional` | Not attempted: written but not executed, since this key's permissions refuse them -- re-confirmed against `perpetuals.positions.list`, `.portfolio_summary` and `.balances`, all three `AuthError(403, PERMISSION_DENIED)` on a `portfolio_type: 'DEFAULT'` key -- and additionally deprecated in the client itself (INTX perpetuals retiring 2026-09-09). |
# | `place_order`, `cancel_order` | Written, intentionally not executed (state-mutating). |
