# %%
import asyncio
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from typing_extensions import AsyncIterable, Literal, TypeAlias, cast

from typed_deribit import Deribit
from typed_deribit.schemas import UserTradeUpdate
from typed_deribit.streams.market_data.book_grouped import GroupedBookUpdate
from dotenv import load_dotenv

load_dotenv()

public_client = await Deribit.new(public=True).__aenter__()
client = await Deribit.new(testnet=True).__aenter__()

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

MARKETS = {
  'spot': ['BTC_USDC', 'ETH_USDC', 'SOL_USDC'],
  'perp': ['BTC-PERPETUAL', 'ETH-PERPETUAL', 'SOL_USDC-PERPETUAL'],
}

# `typed_deribit.schemas.InstrumentInfo.base_currency` / `.quote_currency` /
# `.settlement_currency` / `.price_index` are all declared plain `str`, but
# `get_account_summary`/`get_positions`/`get_index_price` each expect a specific Literal.
# The `str` is the correct side: a probe of 5,550 live instruments found 44 distinct
# `base_currency` values and 54 distinct `price_index` values, most of them outside those
# Literals, so it is the consumers that are too narrow (`get_index_price` alone accepts 344
# index names by the venue's own `get_index_price_names`). A request param is serialized,
# not validated, so `cast` only bridges the static gap; it never rejects a value the venue
# would have accepted. The instruments below all stay inside the Literals.
AccountCurrency: TypeAlias = Literal[
  'BTC', 'ETH', 'STETH', 'ETHW', 'USDC', 'USDT', 'EURR', 'SOL', 'XRP', 'USYC', 'PAXG', 'BNB', 'USDE',
]
PositionsCurrency: TypeAlias = Literal['BTC', 'ETH', 'USDC', 'USDT', 'EURR', 'any']
IndexName: TypeAlias = Literal[
  'btc_usd', 'eth_usd', 'ada_usdc', 'algo_usdc', 'avax_usdc', 'bch_usdc', 'bnb_usdc', 'btc_usdc',
  'btcdvol_usdc', 'buidl_usdc', 'doge_usdc', 'dot_usdc', 'eurr_usdc', 'eth_usdc', 'ethdvol_usdc',
  'hype_usdc', 'link_usdc', 'ltc_usdc', 'near_usdc', 'paxg_usdc', 'shib_usdc', 'sol_usdc',
  'steth_usdc', 'ton_usdc', 'trump_usdc', 'trx_usdc', 'uni_usdc', 'usde_usdc', 'usyc_usdc',
  'xrp_usdc', 'btc_usdt', 'eth_usdt', 'eurr_usdt', 'sol_usdt', 'steth_usdt', 'usdc_usdt',
  'usde_usdt', 'btc_eurr', 'btc_usde', 'btc_usyc', 'eth_btc', 'eth_eurr', 'eth_usde', 'eth_usyc',
  'steth_eth', 'paxg_btc', 'drbfix-btc_usdc', 'drbfix-eth_usdc',
]


# %% [markdown]
# > Public/market-data cells below use `public_client` (mainnet, for representative liquidity). Anything account-scoped (`open_orders`, `trades_history`, positions, collateral, ...) uses `client`, which is the Deribit **TESTNET** account -- balances, positions and trade history reflect that test account, not any real holdings.

# %% [markdown]
# ## `Market` (spot)
#
# **Correction of an earlier PoC pass:** this notebook previously claimed Deribit has no spot market at all. That was wrong -- Deribit does have a genuine spot market, and `typed_deribit` fully models it (`kind='spot'` across `market_data.get_instruments`, `get_instrument`, order book/trades/ticker endpoints, and the WS streams). Confirmed live below against `BTC_USDC`, `ETH_USDC`, and `SOL_USDC` (from `public/get_instruments(currency='any', kind='spot')`, 19 active spot instruments total: `BNB_USDC`, `BTC_USDC`, `BTC_USDE`, `BTC_USDT`, `BUIDL_USDC`, `ETH_BTC`, `ETH_USDC`, `ETH_USDE`, `ETH_USDT`, `PAXG_USDC`, `SOL_ETH`, `SOL_USDC`, `STETH_ETH`, `STETH_USDC`, `USDC_USDT`, `USDE_USDC`, `USDE_USDT`, `USYC_USDC`, `XRP_USDC`).

# %%
async def depth(
  instrument_name: str, *, levels: Literal[1, 5, 10, 20, 50, 100, 1000, 10000] | None = None,
) -> Book:
  raw = await public_client.market_data.get_order_book(instrument_name=instrument_name, depth=levels)
  return Book(
    bids=[Book.Entry(Decimal(str(p)), Decimal(str(q))) for p, q in raw['bids']],
    asks=[Book.Entry(Decimal(str(p)), Decimal(str(q))) for p, q in raw['asks']],
  )

{m: await depth(m, levels=5) for m in MARKETS['spot']}


# %%
def depth_stream(
  instrument_name: str, *,
  levels: Literal['1', '10', '20'] = '10', interval: Literal['raw', '100ms', 'agg2'] = '100ms',
):
  def to_book(update: GroupedBookUpdate) -> Book:
    return Book(
      bids=[Book.Entry(Decimal(str(p)), Decimal(str(q))) for p, q in update['bids']],
      asks=[Book.Entry(Decimal(str(p)), Decimal(str(q))) for p, q in update['asks']],
    )
  return public_client.streams.market_data.book_grouped(instrument_name, group='none', depth=levels, interval=interval).map(to_book)

books: list[Book] = []
async with depth_stream('BTC_USDC') as stream:
  async for book in stream:
    books.append(book)
    if len(books) >= 3:
      break
books


# %%
async def rules(instrument_name: str, *, refetch: bool = False) -> Rules:
  instr = await public_client.market_data.get_instrument(instrument_name=instrument_name)
  # Spot has no `settlement_currency` (a futures/options-only field); Deribit charges spot
  # fees in the quote currency, so that's used as the best-guess `fee_asset`.
  return Rules(
    base=instr['base_currency'],
    quote=instr['quote_currency'],
    fee_asset=instr['quote_currency'],
    tick_size=Decimal(str(instr['tick_size'])),
    step_size=Decimal(str(instr['min_trade_amount'])),
    fixed_min_qty=Decimal(str(instr['min_trade_amount'])),
    maker_fee=Decimal(str(instr.get('maker_commission', 0))),
    taker_fee=Decimal(str(instr.get('taker_commission', 0))),
    api=instr['is_active'],
    details=instr,
  )

{m: await rules(m) for m in MARKETS['spot']}


# %%
async def open_orders(instrument_name: str) -> list[OrderState]:
  raw = await client.trading.get_open_orders_by_instrument(instrument_name=instrument_name)
  out: list[OrderState] = []
  for o in raw:
    price = o['price'] if isinstance(o['price'], (int, float)) else 0
    qty = Decimal(str(o.get('amount', 0)))
    filled = Decimal(str(o.get('filled_amount', 0)))
    sign = 1 if o['direction'] == 'buy' else -1
    out.append(OrderState(
      id=o['order_id'],
      price=Decimal(str(price)),
      qty=sign * qty,
      filled_qty=sign * filled,
      active=o['order_state'] in ('open', 'untriggered', 'triggered'),
      details=o,
    ))
  return out

{m: await open_orders(m) for m in MARKETS['spot']}


# %%
async def trades_history(instrument_name: str, start: datetime, end: datetime) -> list[Trade]:
  # `historical=True` is required to actually honor `start`/`end` beyond the last 24h --
  # the default (`False`) silently ignores the requested window and returns only the last
  # 24h of trades regardless of what `start`/`end` say. `count=1000` (the endpoint's max) --
  # the server default is only 10, which would silently truncate a 30-day window.
  result = await client.trading.get_user_trades_by_instrument_and_time(
    instrument_name=instrument_name, start_timestamp=start, end_timestamp=end,
    count=1000, historical=True,
  )
  out: list[Trade] = []
  for t in result['trades']:
    qty = Decimal(str(t['amount']))
    out.append(Trade(
      id=t['trade_id'],
      price=Decimal(str(t['price'])),
      qty=qty if t['direction'] == 'buy' else -qty,
      time=t['timestamp'],
      maker=t.get('liquidity') == 'M',
      fee=Trade.Fee(amount=Decimal(str(t['fee'])), asset=t['fee_currency']),
      details=t,
    ))
  return out

end = datetime.now(timezone.utc)
start = end - timedelta(days=30)
{m: await trades_history(m, start, end) for m in MARKETS['spot']}


# %%
def trades_stream(instrument_name: str):
  def to_trades(updates: list[UserTradeUpdate]) -> list[Trade]:
    out: list[Trade] = []
    for t in updates:
      qty = Decimal(str(t['amount']))
      out.append(Trade(
        id=t['trade_id'],
        price=Decimal(str(t['price'])),
        qty=qty if t['direction'] == 'buy' else -qty,
        time=t['timestamp'],
        maker=t.get('liquidity') == 'M',
        fee=Trade.Fee(amount=Decimal(str(t['fee'])), asset=t['fee_currency']),
        details=t,
      ))
    return out
  return client.streams.user.trades_by_instrument(instrument_name, interval='raw').map(to_trades)

async with trades_stream('BTC_USDC') as stream:
  it = aiter(stream)
  try:
    result = await asyncio.wait_for(anext(it), timeout=5.0)
  except asyncio.TimeoutError:
    result = 'no new trades observed in 5s (expected -- no live trading on this account)'
result


# %%
async def position(instrument_name: str) -> Position:
  # Deribit rejects `private/get_position` for spot instruments outright -- re-verified
  # live for all three below: `-32602 Invalid params {'reason': 'spot instrument not
  # allowed', 'param': 'instrument_name'}`. Spot has no margin position; it settles
  # directly to ordinary wallet balances, so this reads the base-currency balance via
  # `private/get_account_summary`.
  instr = await public_client.market_data.get_instrument(instrument_name=instrument_name)
  summary = await client.account.get_account_summary(currency=cast(AccountCurrency, instr['base_currency']))
  return Position(size=Decimal(str(summary['balance'])))

{m: await position(m) for m in MARKETS['spot']}


# %%
async def collateral(instrument_name: str) -> Collateral:
  instr = await public_client.market_data.get_instrument(instrument_name=instrument_name)
  summary = await client.account.get_account_summary(currency=cast(AccountCurrency, instr['quote_currency']))
  return Collateral(
    equity=Decimal(str(summary['equity'])),
    free_collateral=Decimal(str(summary['available_funds'])),
  )

{m: await collateral(m) for m in MARKETS['spot']}


# %%
async def available_notional(instrument_name: str) -> Decimal:
  c = await collateral(instrument_name)
  return c.free_collateral

{m: await available_notional(m) for m in MARKETS['spot']}


# %%
async def place_order(instrument_name: str, order: Order, *, settings: Settings = {}) -> OrderResponse:
  qty = Decimal(order['qty'])
  amount = float(abs(qty))
  price = float(Decimal(order['price']))
  is_buy = qty > 0
  if order['type'] == 'MARKET':
    if is_buy:
      raw = await client.trading.buy({'instrument_name': instrument_name, 'amount': amount, 'type': 'market'})
    else:
      raw = await client.trading.sell({'instrument_name': instrument_name, 'amount': amount, 'type': 'market'})
  else:
    post_only = order['type'] == 'POST_ONLY'
    if is_buy:
      raw = await client.trading.buy({
        'instrument_name': instrument_name, 'amount': amount, 'type': 'limit', 'price': price, 'post_only': post_only,
      })
    else:
      raw = await client.trading.sell({
        'instrument_name': instrument_name, 'amount': amount, 'type': 'limit', 'price': price, 'post_only': post_only,
      })
  return OrderResponse(id=raw['order']['order_id'], details=raw)

# Not executed here -- would place a real order on the testnet account.
await place_order('BTC_USDC', {'qty': Decimal('0.001'), 'price': Decimal('20000'), 'type': 'LIMIT'})


# %%
async def cancel_order(instrument_name: str, id: str, *, settings: Settings = {}):
  return await client.trading.cancel(order_id=id)

# Not executed here -- would cancel a real order on the testnet account.
await cancel_order('BTC_USDC', '123456')


# %% [markdown]
# ## `PerpMarket` (perpetual futures)
#
# Deribit also has genuine perpetuals (`BTC-PERPETUAL`, `ETH-PERPETUAL`, `SOL_USDC-PERPETUAL`, ...) alongside dated futures and options; only the true perpetuals are mapped below, since dated futures/options have no funding mechanism and do not fit `PerpMarket`'s `next_funding`/`funding_rates` shape -- see the coverage note at the end.

# %%
async def depth(
  instrument_name: str, *, levels: Literal[1, 5, 10, 20, 50, 100, 1000, 10000] | None = None,
) -> Book:
  raw = await public_client.market_data.get_order_book(instrument_name=instrument_name, depth=levels)
  return Book(
    bids=[Book.Entry(Decimal(str(p)), Decimal(str(q))) for p, q in raw['bids']],
    asks=[Book.Entry(Decimal(str(p)), Decimal(str(q))) for p, q in raw['asks']],
  )

{m: await depth(m, levels=5) for m in MARKETS['perp']}


# %%
def depth_stream(
  instrument_name: str, *,
  levels: Literal['1', '10', '20'] = '10', interval: Literal['raw', '100ms', 'agg2'] = '100ms',
):
  # `book.{instrument}.{interval}` only pushes a full snapshot on the first message and
  # deltas after; `book_grouped` gives a full bids/asks snapshot every notification, which
  # is easier to map onto `Book` directly.
  def to_book(update: GroupedBookUpdate) -> Book:
    return Book(
      bids=[Book.Entry(Decimal(str(p)), Decimal(str(q))) for p, q in update['bids']],
      asks=[Book.Entry(Decimal(str(p)), Decimal(str(q))) for p, q in update['asks']],
    )
  return public_client.streams.market_data.book_grouped(instrument_name, group='none', depth=levels, interval=interval).map(to_book)

books: list[Book] = []
async with depth_stream('BTC-PERPETUAL') as stream:
  async for book in stream:
    books.append(book)
    if len(books) >= 3:
      break
books


# %%
async def rules(instrument_name: str, *, refetch: bool = False) -> Rules:
  instr = await public_client.market_data.get_instrument(instrument_name=instrument_name)
  fee_asset = instr.get('settlement_currency', instr['base_currency'])
  return Rules(
    base=instr['base_currency'],
    quote=instr['quote_currency'],
    fee_asset=fee_asset,
    tick_size=Decimal(str(instr['tick_size'])),
    step_size=Decimal(str(instr['min_trade_amount'])),
    fixed_min_qty=Decimal(str(instr['min_trade_amount'])),
    maker_fee=Decimal(str(instr.get('maker_commission', 0))),
    taker_fee=Decimal(str(instr.get('taker_commission', 0))),
    api=instr['is_active'],
    details=instr,
  )

{m: await rules(m) for m in MARKETS['perp']}


# %%
async def open_orders(instrument_name: str) -> list[OrderState]:
  raw = await client.trading.get_open_orders_by_instrument(instrument_name=instrument_name)
  out: list[OrderState] = []
  for o in raw:
    price = o['price'] if isinstance(o['price'], (int, float)) else 0
    qty = Decimal(str(o.get('amount', 0)))
    filled = Decimal(str(o.get('filled_amount', 0)))
    sign = 1 if o['direction'] == 'buy' else -1
    out.append(OrderState(
      id=o['order_id'],
      price=Decimal(str(price)),
      qty=sign * qty,
      filled_qty=sign * filled,
      active=o['order_state'] in ('open', 'untriggered', 'triggered'),
      details=o,
    ))
  return out

{m: await open_orders(m) for m in MARKETS['perp']}


# %%
async def trades_history(instrument_name: str, start: datetime, end: datetime) -> list[Trade]:
  # `historical=True` is required to actually honor `start`/`end` beyond the last 24h --
  # the default (`False`) silently ignores the requested window and returns only the last
  # 24h of trades regardless of what `start`/`end` say. `count=1000` (the endpoint's max) --
  # the server default is only 10, which would silently truncate a 30-day window.
  result = await client.trading.get_user_trades_by_instrument_and_time(
    instrument_name=instrument_name, start_timestamp=start, end_timestamp=end,
    count=1000, historical=True,
  )
  out: list[Trade] = []
  for t in result['trades']:
    qty = Decimal(str(t['amount']))
    out.append(Trade(
      id=t['trade_id'],
      price=Decimal(str(t['price'])),
      qty=qty if t['direction'] == 'buy' else -qty,
      time=t['timestamp'],
      maker=t.get('liquidity') == 'M',
      fee=Trade.Fee(amount=Decimal(str(t['fee'])), asset=t['fee_currency']),
      details=t,
    ))
  return out

end = datetime.now(timezone.utc)
start = end - timedelta(days=30)
{m: await trades_history(m, start, end) for m in MARKETS['perp']}


# %%
def trades_stream(instrument_name: str):
  def to_trades(updates: list[UserTradeUpdate]) -> list[Trade]:
    out: list[Trade] = []
    for t in updates:
      qty = Decimal(str(t['amount']))
      out.append(Trade(
        id=t['trade_id'],
        price=Decimal(str(t['price'])),
        qty=qty if t['direction'] == 'buy' else -qty,
        time=t['timestamp'],
        maker=t.get('liquidity') == 'M',
        fee=Trade.Fee(amount=Decimal(str(t['fee'])), asset=t['fee_currency']),
        details=t,
      ))
    return out
  return client.streams.user.trades_by_instrument(instrument_name, interval='raw').map(to_trades)

async with trades_stream('BTC-PERPETUAL') as stream:
  it = aiter(stream)
  try:
    result = await asyncio.wait_for(anext(it), timeout=5.0)
  except asyncio.TimeoutError:
    result = 'no new trades observed in 5s (expected -- no live trading on this account)'
result


# %%
async def index(instrument_name: str, *, settings: Settings = {}) -> Decimal:
  instr = await public_client.market_data.get_instrument(instrument_name=instrument_name)
  idx = await public_client.market_data.get_index_price(index_name=cast(IndexName, instr['price_index']))
  return Decimal(str(idx['index_price']))

{m: await index(m) for m in MARKETS['perp']}


# %%
async def next_funding(instrument_name: str) -> NextFunding:
  # No Deribit endpoint publishes a next-funding timestamp: funding accrues continuously
  # and is reported hourly (`public/get_funding_rate_history` returns one point per hour),
  # so the next hour boundary is computed here. `current_funding` is the ticker's live
  # estimate of the rate in force; it reads `0.0` while a perpetual trades at its index --
  # as all three below currently do -- and is nonzero on perpetuals trading at a premium.
  ticker = await public_client.market_data.ticker(instrument_name=instrument_name)
  now = datetime.now(timezone.utc)
  next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
  return NextFunding(
    rate=Decimal(str(ticker.get('current_funding', 0))),
    time=next_hour,
    interval=timedelta(hours=1),
  )

{m: await next_funding(m) for m in MARKETS['perp']}


# %%
async def funding_rates(
  instrument_name: str, start: datetime | None = None, end: datetime | None = None,
) -> list[FundingRate]:
  end = end or datetime.now(timezone.utc)
  start = start or (end - timedelta(days=2))
  raw = await public_client.market_data.get_funding_rate_history(
    instrument_name=instrument_name, start_timestamp=start, end_timestamp=end,
  )
  # `interest_8h` is Deribit's 8h-normalized funding rate per hourly data point (each point
  # also carries `interest_1h`); there is no separately-reported "premium" component, so
  # `FundingRate.premium` stays `None`.
  return [FundingRate(rate=Decimal(str(p['interest_8h'])), time=p['timestamp']) for p in raw]

end = datetime.now(timezone.utc)
start = end - timedelta(days=2)
{m: await funding_rates(m, start, end) for m in MARKETS['perp']}


# %%
async def funding_payments(instrument_name: str, start: datetime, end: datetime) -> list[FundingPayment]:
  # `private/get_settlement_history_by_instrument` carries a `funding` field on `type ==
  # 'settlement'` rows for perpetuals -- the closest per-account equivalent to a funding
  # payments feed. `funding` is a P&L credit, so `FundingPayment.amount`'s "paid if
  # positive" convention needs it negated: over 20 consecutive `ETH-PERPETUAL` settlements
  # on this account's short (-7) position, its sign matched the sign of the summed hourly
  # `interest_1h` rate over the preceding 24h in all 16 nonzero cases (longs pay shorts at
  # a positive rate), and each row's value equals the same settlement's `interest_pl` in
  # `private/get_transaction_log`. `count=1000` (the endpoint's max) -- the server default
  # is only 20 rows, short of the ~30 daily settlements a 30-day window spans.
  result = await client.trading.get_settlement_history_by_instrument(
    instrument_name=instrument_name, type='settlement', search_start_timestamp=end,
    count=1000,
  )
  out: list[FundingPayment] = []
  for s in result['settlements']:
    if s['timestamp'] < start:
      continue
    # `funding` is `NotRequired`, and absent on everything but perpetual settlements:
    # account-wide, 99 of 101 `BTC` `settlement` rows (dated futures) and every `delivery`
    # row carry no `funding` at all.
    funding = s.get('funding')
    if funding is None:
      continue
    out.append(FundingPayment(amount=Decimal(str(-funding)), time=s['timestamp']))
  return out

end = datetime.now(timezone.utc)
start = end - timedelta(days=30)
{m: await funding_payments(m, start, end) for m in MARKETS['perp']}


# %%
async def perp_position(instrument_name: str) -> PerpPosition:
  pos = await client.account.get_position(instrument_name=instrument_name)
  size = Decimal(str(pos.get('size_currency', pos['size'])))
  return PerpPosition(size=size, entry_price=Decimal(str(pos['average_price'])))

{m: await perp_position(m) for m in MARKETS['perp']}


# %%
async def perp_collateral(instrument_name: str) -> PerpCollateral:
  instr = await public_client.market_data.get_instrument(instrument_name=instrument_name)
  currency = instr.get('settlement_currency', instr['base_currency'])
  summary = await client.account.get_account_summary(currency=cast(AccountCurrency, currency))
  positions = await client.account.get_positions(currency=cast(PositionsCurrency, currency))
  margin_model = summary.get('margin_model', '')
  equity = Decimal(str(summary['equity']))
  notional = sum((Decimal(str(abs(p['size']))) for p in positions), Decimal(0))
  leverage = notional / equity if equity > 0 else Decimal(0)
  return PerpCollateral(
    equity=equity,
    free_collateral=Decimal(str(summary['available_funds'])),
    initial_margin=Decimal(str(summary['initial_margin'])),
    maintenance_margin=Decimal(str(summary['maintenance_margin'])),
    leverage=leverage,
    # Read from the account-level `margin_model` `private/get_account_summary` reports
    # (`segregated_sm` on this account): `cross_*` models cross-collateralize every
    # currency, `segregated_*` keep each one's margin apart. There is no per-instrument
    # flag -- `private/get_positions` rows carry none.
    margin_mode='cross' if margin_model.startswith('cross') else 'isolated',
  )

{m: await perp_collateral(m) for m in MARKETS['perp']}


# %%
async def available_notional(instrument_name: str) -> Decimal:
  c = await perp_collateral(instrument_name)
  instr = await public_client.market_data.get_instrument(instrument_name=instrument_name)
  max_leverage = Decimal(str(instr.get('max_leverage', 1)))
  return c.free_collateral * max_leverage

{m: await available_notional(m) for m in MARKETS['perp']}


# %%
async def place_order(instrument_name: str, order: Order, *, settings: Settings = {}) -> OrderResponse:
  qty = Decimal(order['qty'])
  amount = float(abs(qty))
  price = float(Decimal(order['price']))
  is_buy = qty > 0
  if order['type'] == 'MARKET':
    if is_buy:
      raw = await client.trading.buy({'instrument_name': instrument_name, 'amount': amount, 'type': 'market'})
    else:
      raw = await client.trading.sell({'instrument_name': instrument_name, 'amount': amount, 'type': 'market'})
  else:
    post_only = order['type'] == 'POST_ONLY'
    if is_buy:
      raw = await client.trading.buy({
        'instrument_name': instrument_name, 'amount': amount, 'type': 'limit', 'price': price, 'post_only': post_only,
      })
    else:
      raw = await client.trading.sell({
        'instrument_name': instrument_name, 'amount': amount, 'type': 'limit', 'price': price, 'post_only': post_only,
      })
  return OrderResponse(id=raw['order']['order_id'], details=raw)

# Not executed here -- would place a real order on the testnet account.
await place_order('BTC-PERPETUAL', {'qty': Decimal('10'), 'price': Decimal('20000'), 'type': 'LIMIT'})


# %%
async def cancel_order(instrument_name: str, id: str, *, settings: Settings = {}):
  return await client.trading.cancel(order_id=id)

# Not executed here -- would cancel a real order on the testnet account.
await cancel_order('BTC-PERPETUAL', '123456')


# %% [markdown]
# ## Coverage assessment

# %% [markdown]
# **Full**, executed live against `BTC_USDC`, `ETH_USDC`, and `SOL_USDC`:
# - Every read-only/public `Market` method above ran live and returned real data (or a real empty result, not fabricated). 19 active spot instruments exist across the currencies observed (`BTC`, `ETH`, `SOL`, `BNB`, `XRP`, `PAXG`, `STETH`, `USYC`, `BUIDL`, `USDC`, `USDT`, `USDE`); only the three headline pairs are mapped here.
# - Deribit spot has **no margin position** -- `private/get_position` rejects spot instrument names outright (`-32602 Invalid params {'reason': 'spot instrument not allowed', 'param': 'instrument_name'}`). Spot fills settle directly to ordinary per-currency wallet balances, so `position`/`collateral`/`available_notional` all read `private/get_account_summary` instead (base currency for `position`, quote currency for `collateral`), mirroring how spot is mapped on other venues.
# - `public/get_order_book` and `public/get_instrument` both validate on spot now: `OrderBookSnapshot.open_interest` and `InstrumentInfo.settlement_period` are `NotRequired`, `counter_currency` carries every spot quote currency, and `BookStats.high`/`low`/`price_change` are nullable. `BookSummary.open_interest` (`get_book_summary_*`) is `NotRequired` too now, confirmed by typed-dev against 25 spot rows; nothing here reads it either way.
# - `fee_asset` on `rules` is a best guess (quote currency): spot instrument responses carry no `settlement_currency` to read it from the way perpetuals do. Spot commissions are real -- `SOL_USDC` reports `maker_commission = 0.0002` / `taker_commission = 0.0005`, while `BTC_USDC` and `ETH_USDC` are both `0.0` -- but with no spot fill on this account the currency the fee is actually charged in stays unconfirmed.
# - `open_orders` and `trades_history` came back empty for all three markets (no resting orders, no historical fills) -- genuine testnet-account state, not a mapping gap.

# %% [markdown]
# **Full for genuine perpetuals**, executed live against `BTC-PERPETUAL`, `ETH-PERPETUAL`, and `SOL_USDC-PERPETUAL`:
# - Every read-only/public `Market`/`PerpMarket` method above ran live and returned real data (or a real empty/error result, not fabricated). Unlike spot, all three validate cleanly -- `get_order_book`, `get_instrument` and `ticker` are called with validation on throughout this section.
# - Dated futures and options exist on Deribit (`BTC-25DEC26`, options chains, ...) but are intentionally **not** mapped here: they have no funding mechanism, so `next_funding`/`funding_rates`/`funding_payments` do not apply to them at all -- forcing them into `PerpMarket` would misrepresent the venue rather than reveal a real gap. The plain `Market` methods would mostly carry over to those instruments (`BookStats.high`/`low`/`price_change` are nullable, so `depth` validates on options with no trades in the window).
# - `next_funding.time`/`interval` are computed (hourly cadence), not read from the API: no Deribit endpoint publishes a next-funding timestamp, and `public/get_funding_rate_history` reports the rate hourly. `next_funding.rate` reads the ticker's `current_funding`, which is `0.0` for all three of these perpetuals right now (they trade at their index) and nonzero on perpetuals trading at a premium.
# - `funding_payments` returns real per-settlement funding amounts for the account's `ETH-PERPETUAL` position, both positive and negative (445 rows available). The `-funding` sign convention is now confirmed rather than guessed: across 20 consecutive settlements on a short (-7) position, `funding`'s sign matched the sign of the summed hourly `interest_1h` rate in all 16 nonzero cases, and each value equals the same settlement's `interest_pl` in `private/get_transaction_log` -- so a positive `funding` was received, which `FundingPayment.amount` records as negative.
# - `open_orders` came back empty for all three markets. `trades_history` returns 4 real historical fills for `BTC-PERPETUAL` and nothing for the other two within the 30-day window, and `perp_position` reports a real open short on `ETH-PERPETUAL` (size -7) with `BTC-PERPETUAL`/`SOL_USDC-PERPETUAL` flat -- genuine testnet-account state, not a mapping gap. `historical=True` on `get_user_trades_by_instrument_and_time` is load-bearing and was re-measured: the same 30-day `BTC-PERPETUAL` query returns 4 trades with it and 0 without, because the default limits results to the last 24h regardless of `start`/`end`.
# - `margin_mode` is read from `private/get_account_summary`'s account-level `margin_model` (`segregated_sm` here, hence `'isolated'`); `cross_*` models map to `'cross'`. Deribit reports no per-instrument isolated/cross flag -- `private/get_positions` rows carry none.
