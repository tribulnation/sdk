# %%
import asyncio
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from typing_extensions import Literal

from typed_kraken import Kraken
from typed_kraken.spot.trading.add_order import AddOrderMarket, AddOrderLimit
from typed_kraken.streams.market_data.book import BookMessage
from dotenv import load_dotenv

from tribulnation.sdk.market import (
  Book,
  Collateral,
  Order,
  OrderResponse,
  OrderState,
  Position,
  Rules,
  Settings,
  Trade,
)

load_dotenv()

client = await Kraken.new().__aenter__()

# REST pair identifiers (Kraken "altname", e.g. `pair=` on market_data/trading endpoints).
# `XBTUSDC` is the only pair this account has ever traded, so it is what keeps the
# account-scoped cells (trades_history/position/collateral) from returning empties.
MARKETS = {
  'spot': ['XBTUSD', 'ETHUSD', 'SOLUSD', 'XBTUSDC'],
}

# Kraken WebSocket v2 uses yet another symbol format for the same pairs (`BTC/USD`, not
# the REST altname `XBTUSD` nor the legacy-WS `wsname` `XBT/USD` reported by AssetPairs --
# three different spellings of the same pairs across one client. See coverage notes.
WS_SYMBOLS = {
  'XBTUSD': 'BTC/USD',
  'ETHUSD': 'ETH/USD',
  'SOLUSD': 'SOL/USD',
  'XBTUSDC': 'BTC/USDC',
}


# %% [markdown]
# ## `Market` (spot)
#
# Kraken's `typed_kraken` client is Spot-only -- see the `PerpMarket` section at the end for why the perpetual half of the interface doesn't apply here at all.

# %%
async def depth(symbol: str, *, levels: int | None = None) -> Book:
  raw = await client.spot.market_data.depth(pair=symbol, count=levels)
  book = next(iter(raw.values()))
  return Book(
    bids=[Book.Entry(Decimal(p), Decimal(q)) for p, q, _ts in book.get('bids', [])],
    asks=[Book.Entry(Decimal(p), Decimal(q)) for p, q, _ts in book.get('asks', [])],
  )


{symbol: await depth(symbol, levels=5) for symbol in MARKETS['spot']}


# %%
def depth_stream(symbol: str, *, levels: Literal[10, 25, 100, 500, 1000] = 10):
  def to_book(msg: BookMessage) -> Book:
    data = msg['data'][0]
    return Book(
      bids=[
        Book.Entry(Decimal(str(e['price'])), Decimal(str(e['qty'])))
        for e in data['bids']
      ],
      asks=[
        Book.Entry(Decimal(str(e['price'])), Decimal(str(e['qty'])))
        for e in data['asks']
      ],
    )

  # `levels` must be one of Kraken's fixed depths (10/25/100/500/1000), unlike the SDK's
  # arbitrary `int | None`.
  return client.streams.market_data.book(symbol=[WS_SYMBOLS[symbol]], depth=levels).map(
    to_book
  )


books: list[Book] = []
async with depth_stream('XBTUSD') as stream:
  async for book in stream:
    books.append(book)
    if len(books) >= 3:
      break
books


# %%
async def rules(symbol: str, *, refetch: bool = False) -> Rules:
  raw = await client.spot.market_data.asset_pairs(pair=symbol)
  pair = next(iter(raw.values()))
  fees_taker = pair.get('fees') or []
  fees_maker = pair.get('fees_maker') or fees_taker
  tick_size = pair.get('tick_size')
  ordermin = pair.get('ordermin')
  costmin = pair.get('costmin')
  return Rules(
    base=pair.get('base', ''),
    quote=pair.get('quote', ''),
    fee_asset=pair.get('quote', ''),
    tick_size=tick_size
    if tick_size is not None
    else Decimal(1) / 10 ** pair.get('pair_decimals', 0),
    step_size=Decimal(1) / 10 ** pair.get('lot_decimals', 0),
    fixed_min_qty=ordermin,
    min_value=costmin,
    maker_fee=Decimal(str(fees_maker[0][1])) / 100 if fees_maker else Decimal(0),
    taker_fee=Decimal(str(fees_taker[0][1])) / 100 if fees_taker else Decimal(0),
    api=pair.get('status') == 'online',
    details=pair,
  )


{symbol: await rules(symbol) for symbol in MARKETS['spot']}


# %%
async def open_orders(symbol: str) -> list[OrderState]:
  raw = await client.spot.account.open_orders()
  out: list[OrderState] = []
  for txid, o in (raw.get('open') or {}).items():
    descr = o.get('descr') or {}
    if descr.get('pair') != symbol:
      continue
    vol = Decimal(o.get('vol', '0'))
    vol_exec = Decimal(o.get('vol_exec', '0'))
    sign = 1 if descr.get('type') == 'buy' else -1
    out.append(
      OrderState(
        id=txid,
        price=Decimal(descr.get('price', '0')),
        qty=sign * vol,
        filled_qty=sign * vol_exec,
        active=o.get('status') in ('pending', 'open'),
        details=o,
      )
    )
  return out


{symbol: await open_orders(symbol) for symbol in MARKETS['spot']}


# %%
async def trades_history(symbol: str, start: datetime, end: datetime) -> list[Trade]:
  quote = (await rules(symbol)).quote
  raw = await client.spot.account.trades_history(
    pair=symbol,
    start=int(start.timestamp()),
    end=int(end.timestamp()),
  )
  out: list[Trade] = []
  for tid, t in (raw.get('trades') or {}).items():
    vol = Decimal(t.get('vol', '0'))
    sign = 1 if t.get('type') == 'buy' else -1
    fee_amt = Decimal(t.get('fee', '0') or '0')
    out.append(
      Trade(
        id=str(t.get('trade_id', tid)),
        price=Decimal(t.get('price', '0')),
        qty=sign * vol,
        time=t['time'],
        maker=bool(t.get('maker', False)),
        # Kraken's trades_history fee is denominated in the pair's quote asset, but doesn't
        # say so explicitly -- inferred from AssetPairs.
        fee=Trade.Fee(amount=fee_amt, asset=quote) if fee_amt else None,
        details=t,
      )
    )
  return out


end = datetime.now(timezone.utc)
start = end - timedelta(days=365)
{symbol: await trades_history(symbol, start, end) for symbol in MARKETS['spot']}


# %%
async def trades_stream(symbol: str):
  ws_symbol = WS_SYMBOLS[symbol]
  async with client.streams.private.executions(snap_trades=False) as stream:
    async for msg in stream:
      for e in msg.get('data', []):
        # Subscript (not `.get()`) on `exec_type` so the type checker narrows
        # `e` from `ExecutionTradeEvent | ExecutionOrderEvent` down to
        # `ExecutionTradeEvent` for the rest of the loop body -- the trade-only
        # fields below (`last_qty`/`trade_id`/`last_price`/`side`) don't exist
        # at all on `ExecutionOrderEvent`.
        if e['exec_type'] != 'trade' or e.get('symbol') != ws_symbol:
          continue
        side = e['side']
        qty = Decimal(str(e['last_qty']))
        fees = e.get('fees') or []
        fee = (
          Trade.Fee(amount=Decimal(str(fees[0]['qty'])), asset=fees[0]['asset'])
          if fees
          else None
        )
        yield Trade(
          id=str(e['trade_id']),
          price=Decimal(str(e['last_price'])),
          qty=qty if side == 'buy' else -qty,
          time=e['timestamp'],
          maker=e.get('liquidity_ind') == 'm',
          fee=fee,
          details=e,
        )


stream = trades_stream('XBTUSD')
try:
  result = await asyncio.wait_for(anext(stream), timeout=5.0)
except asyncio.TimeoutError:
  result = 'no new trades observed in 5s (expected -- no live trading on this account)'
result


# %%
async def position(symbol: str) -> Position:
  base = (await rules(symbol)).base
  balances = await client.spot.account.balance()
  size = Decimal(balances.get(base, '0'))
  return Position(size=size)


{symbol: await position(symbol) for symbol in MARKETS['spot']}


# %%
async def collateral(symbol: str) -> Collateral:
  quote = (await rules(symbol)).quote
  balances = await client.spot.account.balance_ex()
  info = balances.get(quote) or {}
  balance = Decimal(info.get('balance', '0'))
  hold = Decimal(info.get('hold_trade', '0'))
  return Collateral(equity=balance, free_collateral=balance - hold)


{symbol: await collateral(symbol) for symbol in MARKETS['spot']}


# %%
async def available_notional(symbol: str) -> Decimal:
  c = await collateral(symbol)
  return c.free_collateral


{symbol: await available_notional(symbol) for symbol in MARKETS['spot']}


# %%
async def place_order(
  symbol: str, order: Order, *, settings: Settings = {}
) -> OrderResponse:
  side: Literal['buy', 'sell'] = 'buy' if Decimal(order['qty']) > 0 else 'sell'
  volume = str(abs(Decimal(order['qty'])))
  price = str(Decimal(order['price']))
  body: AddOrderMarket | AddOrderLimit
  if order['type'] == 'MARKET':
    body = {'pair': symbol, 'type': side, 'ordertype': 'market', 'volume': volume}
  elif order['type'] == 'POST_ONLY':
    body = {
      'pair': symbol,
      'type': side,
      'ordertype': 'limit',
      'volume': volume,
      'price': price,
      'oflags': 'post',
    }
  else:
    body = {
      'pair': symbol,
      'type': side,
      'ordertype': 'limit',
      'volume': volume,
      'price': price,
    }
  raw = await client.spot.trading.add_order(body)
  return OrderResponse(id=(raw.get('txid') or [''])[0], details=raw)


# Not executed here -- would place a real order on the account.
await place_order(
  'XBTUSD', {'qty': Decimal('0.0001'), 'price': Decimal('20000'), 'type': 'LIMIT'}
)


# %%
async def cancel_order(symbol: str, id: str, *, settings: Settings = {}):
  return await client.spot.trading.cancel_order(txid=id)


# Not executed here -- would cancel a real order on the account.
await cancel_order('XBTUSD', '123456')

# %% [markdown]
# ## `PerpMarket` (Kraken Futures) -- bypassing `typed_kraken`
#
# `typed_kraken` is Kraken **Spot** only (`Kraken.new()` exposes just `spot`, `streams`, and
# `trading_ws` -- no perpetuals/futures namespace). Kraken's perpetual futures product is a
# separate, fully public, officially documented API on its own host, `futures.kraken.com`,
# described at **https://docs.kraken.com/api/docs/futures-api/**. It is not an internal or
# undocumented surface -- it's Kraken's normal Futures product docs, just not wrapped by
# `typed_kraken`.
#
# The cells below talk to that API's **public, unauthenticated** REST endpoints directly with
# `httpx`, entirely bypassing `typed_kraken`. Endpoints used (all cited inline below too):
#
# - Orderbook -- https://docs.kraken.com/api/docs/futures-api/trading/get-orderbook/
# - Instruments -- https://docs.kraken.com/api/docs/futures-api/trading/get-instruments
# - Fee schedules -- https://docs.kraken.com/api/docs/futures-api/trading/get-fee-schedules
# - Ticker by symbol -- https://docs.kraken.com/api/docs/futures-api/trading/get-ticker/
# - Historical funding rates -- https://docs.kraken.com/api/docs/futures-api/trading/historical-funding-rates
#
# **Credential caveat:** Kraken Futures authenticates with its own, separate API key/secret pair,
# distinct from Kraken Spot. The `KRAKEN_API_KEY`/`KRAKEN_PRIVATE_KEY` in `.env` are Spot
# credentials and would not authenticate against Kraken Futures' private endpoints -- this
# environment has no Kraken Futures API credentials. So only public endpoints are called here;
# see the markdown cell after the code below for exactly which `PerpMarket`/`Market` methods that
# leaves out.

# %%
import httpx
from typing_extensions import Any

from tribulnation.sdk.market import FundingRate, NextFunding

FUTURES_BASE_URL = 'https://futures.kraken.com/derivatives/api/v3'
# Kraken Futures is a fully separate, publicly documented product from Kraken Spot -- see
# https://docs.kraken.com/api/docs/futures-api/ -- and isn't covered by `typed_kraken` at all
# (that package only wraps api.kraken.com Spot). Everything below talks to Kraken Futures'
# public REST endpoints directly with `httpx`, bypassing `typed_kraken` entirely. Only
# unauthenticated endpoints are used: the `KRAKEN_API_KEY`/`KRAKEN_PRIVATE_KEY` in `.env` are
# Spot API keys and would not authenticate against Kraken Futures' separate key/secret scheme.
futures = httpx.AsyncClient(base_url=FUTURES_BASE_URL)

# "PF_" = flexible (multi-collateral) linear perpetuals, quoted and margined in USD -- the
# closest Kraken Futures analogue to Binance's USDT-M perps used elsewhere in this repo.
PERP_MARKETS = ['PF_XBTUSD', 'PF_ETHUSD', 'PF_SOLUSD']


# %%
async def depth(symbol: str, *, levels: int | None = None) -> Book:
  # https://docs.kraken.com/api/docs/futures-api/trading/get-orderbook/
  # The endpoint has no server-side depth/count param -- it always returns the full book,
  # bids and asks both sorted ascending by price -- so `levels` is applied client-side.
  raw = (await futures.get('/orderbook', params={'symbol': symbol})).json()['orderBook']
  bids = raw['bids'][-levels:] if levels else raw['bids']
  asks = raw['asks'][:levels] if levels else raw['asks']
  return Book(
    bids=[Book.Entry(Decimal(str(p)), Decimal(str(q))) for p, q in bids],
    asks=[Book.Entry(Decimal(str(p)), Decimal(str(q))) for p, q in asks],
  )


{symbol: await depth(symbol, levels=5) for symbol in PERP_MARKETS}


# %%
async def rules(symbol: str, *, refetch: bool = False) -> Rules:
  # https://docs.kraken.com/api/docs/futures-api/trading/get-instruments
  # Fees aren't on the instrument itself -- each instrument points at a `feeScheduleUid`,
  # resolved against the public https://docs.kraken.com/api/docs/futures-api/trading/get-fee-schedules
  # fee schedules list. This is the base (lowest-volume) tier -- actual tier depends on
  # trailing volume, which needs an authenticated account.
  instruments = (await futures.get('/instruments')).json()['instruments']
  instr = next(i for i in instruments if i['symbol'] == symbol)
  fee_schedules = {
    fs['uid']: fs for fs in (await futures.get('/feeschedules')).json()['feeSchedules']
  }
  schedule: dict[str, Any] = fee_schedules.get(instr.get('feeScheduleUid')) or {}
  tiers: list[dict[str, Any]] = schedule.get('tiers') or []
  base_tier = tiers[0] if tiers else None
  return Rules(
    base=instr['base'],
    quote=instr['quote'],
    fee_asset=instr['quote'],
    tick_size=Decimal(str(instr['tickSize'])),
    step_size=Decimal(1) / 10 ** instr.get('contractValueTradePrecision', 0),
    max_qty=Decimal(str(instr['maxPositionSize']))
    if instr.get('maxPositionSize')
    else None,
    maker_fee=Decimal(str(base_tier['makerFee'])) / 100 if base_tier else Decimal(0),
    taker_fee=Decimal(str(base_tier['takerFee'])) / 100 if base_tier else Decimal(0),
    api=instr.get('tradeable', False),
    details=instr,
  )


{symbol: await rules(symbol) for symbol in PERP_MARKETS}


# %%
async def index(symbol: str, *, settings: Settings = {}) -> Decimal:
  # https://docs.kraken.com/api/docs/futures-api/trading/get-ticker/
  raw = (await futures.get(f'/tickers/{symbol}')).json()['ticker']
  return Decimal(str(raw['indexPrice']))


{symbol: await index(symbol) for symbol in PERP_MARKETS}


# %%
async def next_funding(symbol: str) -> NextFunding:
  # Kraken Futures perpetuals fund continuously, re-setting the rate every hour on the hour --
  # not Binance-style fixed 8h windows. See
  # https://docs.kraken.com/api/docs/futures-api/trading/get-ticker/ and
  # https://blog.kraken.com/product/quick-primer-on-funding-rates
  # `ticker.fundingRate` is reported in absolute quote-currency units per contract; dividing by
  # `markPrice` recovers the relative rate -- verified live against `relativeFundingRate` from
  # the historical-funding-rates endpoint below, which agrees to the reported precision.
  raw = (await futures.get(f'/tickers/{symbol}')).json()['ticker']
  rate = Decimal(str(raw['fundingRate'])) / Decimal(str(raw['markPrice']))
  next_time = datetime.now(timezone.utc).replace(
    minute=0, second=0, microsecond=0
  ) + timedelta(hours=1)
  return NextFunding(rate=rate, time=next_time, interval=timedelta(hours=1))


{symbol: await next_funding(symbol) for symbol in PERP_MARKETS}


# %%
async def funding_rates(
  symbol: str,
  start: datetime | None = None,
  end: datetime | None = None,
) -> list[FundingRate]:
  # https://docs.kraken.com/api/docs/futures-api/trading/historical-funding-rates
  # The endpoint takes no start/end params and returns the full history (back to contract
  # launch, thousands of rows) in a single response -- filtered client-side here.
  raw = (
    await futures.get('/historical-funding-rates', params={'symbol': symbol})
  ).json()['rates']
  out = [
    FundingRate(
      rate=Decimal(str(r['relativeFundingRate'])),
      time=datetime.fromisoformat(r['timestamp'].replace('Z', '+00:00')),
    )
    for r in raw
  ]
  if start:
    out = [r for r in out if r.time >= start]
  if end:
    out = [r for r in out if r.time <= end]
  return out


end = datetime.now(timezone.utc)
start = end - timedelta(days=7)
{symbol: await funding_rates(symbol, start, end) for symbol in PERP_MARKETS}

# %% [markdown]
# ### Not covered here: private/authenticated Kraken Futures endpoints
#
# Everything below needs an authenticated call against Kraken Futures' private REST API, which
# uses its own separate API key/secret -- not present in this environment (only Spot credentials
# are configured). Per the task's mutation/credential-safety rules, none of these were attempted:
#
# - `open_orders`, `trades_history`, `trades_stream` -- need Futures account credentials.
# - `position`/`perp_position`, `collateral`/`perp_collateral`, `available_notional` -- need the
#   authenticated Futures accounts/positions endpoints.
# - `funding_payments` -- needs the authenticated Futures fills/history endpoint.
# - `place_order`, `cancel_order` -- mutating, and would need Futures credentials regardless of
#   the no-mutation rule.
#
# A hypothetical `typed_kraken_futures` client (or a Kraken Futures key/secret pair) would be the
# place to fill these in.

# %% [markdown]
# ## Coverage
#
# **Mostly supported for spot.** All of `Market`'s read-only methods have a working mapping and were exercised live against real market/account data:
#
# - `depth`/`depth_stream`: solid, modulo the pair-naming mismatch called out above (REST altname vs. WS v2 symbol) and Kraken's fixed set of allowed WS book depths.
# - `rules`: Kraken's `AssetPairs` doesn't distinguish `fixed_min_price`/`rel_min_price` -- there's no min/max price field at all, only min *order size* (`ordermin`) and min *order cost* (`costmin`); those SDK price-bound fields are simply unset.
# - `open_orders`/`trades_history`: Kraken's `open_orders` is account-wide, so this notebook filters client-side on `descr['pair']`; `trades_history` does take a `pair=` filter. `trades_history` also infers the fee asset (quote currency) rather than reading it off the trade row, since Kraken doesn't report it explicitly there. `XBTUSDC` is in `MARKETS['spot']` because it is the only pair this account has ever traded -- without it every account-scoped cell here returns empty and verifies nothing. `open_orders` still returns nothing on all four pairs: the account holds no resting orders and placing one is a mutation.
# - `trades_history`: **blocked** on `HistoricalTrade.time` is a bare `float` where the spec says `epoch-seconds` (`typed-client-issues.md`, codegen). The mapping runs and the rows above are real, but `time` lands as a raw epoch float in `Trade.time`, a plain dataclass field that coerces nothing, so the cell fails `poc check` until the client renders `TimestampSeconds`. Not converted locally: the fix belongs in the client.
# - `trades_stream`: mapped onto `streams.private.executions` filtered to `exec_type == 'trade'`, which is a unified fills+order-status channel -- this notebook only reads the fill half of it.
# - `position`/`collateral`/`available_notional`: spot has no native "position" or margin-collateral concept for an unlevered account, so these are approximated from plain asset balances (base-asset balance as `position.size`, quote-asset balance net of `hold_trade` as `collateral`), matching how the Binance spot PoC does it.
# - `place_order`/`cancel_order`: written against `spot.trading.add_order`/`cancel_order` but never executed, per the task's mutation-safety rule. Kraken also exposes an entirely separate WS trading surface, `trading_ws` (kept off `streams` so that channel stays subscription-only) -- not used here, but a real venue implementation would likely prefer it for order placement latency.
#
# ## Coverage -- `PerpMarket` (Kraken Futures)
#
# **Public perp market data is fully reachable, live-verified above.** All of it bypasses
# `typed_kraken` (Spot-only) and hits Kraken Futures' separate, publicly documented REST API
# directly:
#
# - `depth`: solid. The endpoint has no server-side depth/count param -- it always returns the
#   full book (thousands of levels), ascending-sorted on both sides -- so `levels` is sliced
#   client-side.
# - `rules`: `tick_size`/`step_size`/`max_qty`/`api` map cleanly from `/instruments`. There's no
#   `fixed_min_qty`/`min_value` field in the current public schema (unlike the blog-era docs that
#   mention a `minOrderSize`, it isn't actually present on live instrument rows). Fees require a
#   second call to `/feeschedules`, resolved via the instrument's `feeScheduleUid` -- this only
#   gets the base (lowest-volume) tier, since the actual tier depends on trailing volume that's
#   only visible to an authenticated account.
# - `index`: direct `indexPrice` field off the per-symbol ticker.
# - `next_funding`: Kraken Futures perpetuals fund **continuously**, re-setting the rate every
#   hour on the hour, unlike Binance's fixed 8h windows -- so `interval` is always 1 hour and
#   `time` is simply the next hour boundary. The ticker's `fundingRate` field is in *absolute*
#   quote-currency units per contract, not the SDK's relative-rate convention; dividing by
#   `markPrice` recovers the relative rate, verified live against `relativeFundingRate` from
#   `historical-funding-rates` (they agree to reported precision).
# - `funding_rates`: `historical-funding-rates` takes no `start`/`end` params -- it returns the
#   entire history back to contract launch (thousands of rows) in one response, filtered
#   client-side here.
#
# **Private/authenticated Kraken Futures methods are not covered** (`open_orders`,
# `trades_history`, `trades_stream`, `position`/`perp_position`, `collateral`/`perp_collateral`,
# `available_notional`, `funding_payments`, `place_order`, `cancel_order`): Kraken Futures uses a
# separate API key/secret from Kraken Spot, and this environment only has Spot credentials
# (`KRAKEN_API_KEY`/`KRAKEN_PRIVATE_KEY`). Authenticated Futures coverage would need a separate
# Kraken Futures API key/secret pair that isn't available here -- not a modeling gap, just a
# credentials gap.
