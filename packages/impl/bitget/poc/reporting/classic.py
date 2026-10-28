# %%
import asyncio
import os
from decimal import Decimal
from datetime import datetime, timedelta, timezone

from typing_extensions import (
  Awaitable, Callable, Literal, ParamSpec, Sequence, TypeVar,
)

from typed_bitget import Bitget
from dotenv import load_dotenv

from tribulnation.sdk.reporting import (
  CryptoDeposit,
  CryptoWithdrawal,
  Fee,
  FeeLeg,
  HistoryRecord,
  Observation,
  Position,
  Snapshot,
  SnapshotRecord,
  SpotTrade,
  SubaccountSnapshot,
  UnknownObservation,
  source_id,
)

load_dotenv()

client = await Bitget.new(
  access_key=os.environ['BITGET_CLASSIC_ACCESS_KEY'],
  secret_key=os.environ['BITGET_CLASSIC_SECRET_KEY'],
  passphrase=os.environ['BITGET_CLASSIC_PASSPHRASE'],
).__aenter__()

SPOT_MARKETS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']
PRODUCT_TYPES: list[Literal['USDT-FUTURES', 'COIN-FUTURES', 'USDC-FUTURES']] = [
  'USDT-FUTURES', 'COIN-FUTURES', 'USDC-FUTURES',
]


P = ParamSpec('P')
T = TypeVar('T')
RETRY_ATTEMPTS = 4


async def retry(
  coro_fn: Callable[P, Awaitable[T]], *args: P.args, **kwargs: P.kwargs,
) -> T:
  """Retry a Bitget call a few times with backoff on rate-limit (429) errors.

  `classic.tax.*` in particular shares a tight per-key rate bucket that this notebook's
  own iterative development tripped repeatedly -- not a documented API limitation, just
  practical friction worth working around here.

  A throttled request comes back as HTTP 429 with a body carrying its own `"429"` code,
  which the client classifies by that code into a plain `ApiError('429', ...)` -- so the
  code is matched as a string, and `RateLimited` (reserved for Bitget's own `1001`) never
  shows up here.
  """
  for attempt in range(RETRY_ATTEMPTS):
    try:
      return await coro_fn(*args, **kwargs)
    except Exception as e:
      code = e.args[0] if e.args else None
      if str(code) != '429' or attempt == RETRY_ATTEMPTS - 1:
        raise
      await asyncio.sleep(2 * (attempt + 1))
  raise RuntimeError('retry: exhausted attempts without a response')


# %% [markdown]
# ## `History`
#
# Classic has no single unified activity feed. This notebook maps each *structured* source
# (spot/futures/margin fills, on-chain deposits/withdrawals) directly onto its matching
# `Observation` subtype, plus the per-product-line `tax` endpoints (`classic.tax.*`) as a
# catch-all `UnknownObservation`+`FeeLeg` pair -- the same "flows" role production's
# `tribulnation.bitget.reporting.history` gives them, independently re-derived here against
# `typed_bitget` directly rather than imported from that code.

# %%
async def spot_trades(start: datetime, end: datetime) -> list[SpotTrade]:
  out: list[SpotTrade] = []
  for symbol in SPOT_MARKETS:
    fills = await client.classic.spot.order.fills(symbol=symbol, start_time=start, end_time=end)
    for f in fills:
      size = Decimal(f['size'])
      fee_detail = f['feeDetail']
      fee_amount = abs(Decimal(fee_detail['totalFee']))
      out.append(SpotTrade(
        id=f['tradeId'],
        time=f['cTime'],
        pair=symbol,
        size=size if f['side'] == 'buy' else -size,
        price=Decimal(f['priceAvg']),
        order_id=f['orderId'],
        fee=Fee(amount=fee_amount, asset=fee_detail['feeCoin']) if fee_amount else None,
        subaccount='spot',
      ))
  return out

end = datetime.now(timezone.utc)
start = end - timedelta(hours=24)
await spot_trades(start, end)


# %%
async def futures_trades(start: datetime, end: datetime) -> list[SpotTrade]:
  # Only USDT-FUTURES is walked here for tractability (COIN-FUTURES/USDC-FUTURES use
  # different symbol universes) -- see the coverage note below.
  out: list[SpotTrade] = []
  for symbol in SPOT_MARKETS:
    r = await client.classic.mix.order.fills(
      product_type='USDT-FUTURES', symbol=symbol, start_time=start, end_time=end,
    )
    for f in r['fillList'] or []:
      fee_amount = Decimal(0)
      fee_asset = None
      for detail in f['feeDetail']:
        fee_amount += abs(Decimal(detail['totalFee']))
        fee_asset = detail['feeCoin']
      size = Decimal(f['baseVolume'])
      out.append(SpotTrade(
        id=f['tradeId'],
        time=f['cTime'],
        pair=symbol,
        size=size if f['side'] == 'buy' else -size,
        price=Decimal(f['price']),
        order_id=f['orderId'],
        fee=Fee(amount=fee_amount, asset=fee_asset) if fee_amount and fee_asset else None,
        subaccount='futures',
      ))
  return out

await futures_trades(start, end)


# %%
async def margin_trades(
  margin_type: str, start: datetime, end: datetime,
) -> list[SpotTrade]:
  subaccount = f'{margin_type}_margin'
  fn = (
    client.classic.margin.cross.order.fills
    if margin_type == 'crossed'
    else client.classic.margin.isolated.order.fills
  )
  out: list[SpotTrade] = []
  for symbol in SPOT_MARKETS:
    r = await fn(symbol=symbol, start_time=start, end_time=end)
    for f in r['fills']:
      raw_side = f.get('side') or ''
      side = 'buy' if 'buy' in raw_side else 'sell'
      raw_size = f.get('size')
      size = Decimal(raw_size) if raw_size is not None else None
      fee_detail = f.get('feeDetail')
      fee = None
      if fee_detail:
        fee_coin = fee_detail.get('feeCoin')
        total_fee = fee_detail.get('totalFee')
        fee_amount = abs(Decimal(total_fee)) if total_fee else None
        if fee_amount and fee_coin:
          fee = Fee(amount=fee_amount, asset=fee_coin)
      raw_price = f.get('priceAvg')
      out.append(SpotTrade(
        id=f.get('tradeId'),
        time=f.get('cTime'),
        pair=symbol,
        size=(size if side == 'buy' else -size) if size is not None else None,
        price=Decimal(raw_price) if raw_price is not None else None,
        order_id=f.get('orderId'),
        fee=fee,
        subaccount=subaccount,
      ))
  return out

await margin_trades('crossed', start, end)


# %%
async def crypto_deposits(start: datetime, end: datetime) -> list[CryptoDeposit]:
  raw = await client.classic.spot.deposit.records(start_time=start, end_time=end)
  out: list[CryptoDeposit] = []
  for d in raw:
    if d['dest'] != 'on_chain' or d['status'] != 'success':
      continue
    out.append(CryptoDeposit(
      id=d['orderId'],
      time=d['cTime'],
      asset=d['coin'],
      amount=d['size'],
      network=d['chain'],
      tx_id=d['tradeId'],
      src_address=d.get('fromAddress'),
      dst_address=d['toAddress'],
      subaccount='spot',
    ))
  return out

deposits_end = datetime.now(timezone.utc)
deposits_start = deposits_end - timedelta(days=30)
await crypto_deposits(deposits_start, deposits_end)


# %%
async def crypto_withdrawals(start: datetime, end: datetime) -> list[CryptoWithdrawal]:
  raw = await client.classic.spot.withdrawal.records(start_time=start, end_time=end)
  out: list[CryptoWithdrawal] = []
  for w in raw:
    if w['dest'] != 'on_chain' or w['status'] != 'success':
      continue
    # `fee` arrives signed negative (confirmed live: `-0.0064` on an AVAX withdrawal),
    # while `Fee.amount` is a magnitude.
    fee_amount = abs(w['fee'])
    out.append(CryptoWithdrawal(
      id=w['orderId'],
      time=w['cTime'],
      asset=w['coin'],
      amount=-w['size'],
      network=w['chain'],
      tx_id=w['tradeId'],
      dst_address=w['toAddress'],
      fee=Fee(amount=fee_amount, asset=w['coin']) if fee_amount else None,
      subaccount='spot',
    ))
  return out

await crypto_withdrawals(deposits_start, deposits_end)


# %% [markdown]
# ### `flows` -- tax records as `UnknownObservation` fallback
#
# Bitget's `tax` endpoints report *every* balance-changing event per product line
# (deposits, trades, transfers, fees, liquidations...), tagged with a free-text
# `spotTaxType`/`futureTaxType`/`marginTaxType` that (for spot/futures) isn't a documented
# closed set -- so, like KuCoin's `account.ledgers`, this notebook maps each row to an
# `UnknownObservation` rather than guessing at a precise `Observation` subtype. This
# necessarily **overlaps** with `spot_trades`/`futures_trades`/`margin_trades`/
# `crypto_deposits`/`crypto_withdrawals` above (a trade shows up both as a `SpotTrade` from
# `order.fills` and as an `UnknownObservation` from `tax.spot_records`) -- deduplication is
# out of scope for this demo; a real integration would pick one source per event type, not
# both.

# %%
async def flows(start: datetime, end: datetime) -> list[Observation]:
  out: list[Observation] = []
  spot = await retry(client.classic.tax.spot_records, start_time=start, end_time=end)
  futures = await retry(client.classic.tax.futures_records, start_time=start, end_time=end)
  crossed = await retry(
    client.classic.tax.margin_records, margin_type='crossed', start_time=start, end_time=end,
  )
  isolated = await retry(
    client.classic.tax.margin_records, margin_type='isolated', start_time=start, end_time=end,
  )
  for tx in spot:
    out.append(UnknownObservation(
      id=tx['id'], asset=tx['coin'], amount=tx['amount'], time=tx['ts'], subaccount='spot',
    ))
    if (fee := abs(tx['fee'])) > 0:
      out.append(FeeLeg(
        id=f'{tx["id"]}:fee', asset=tx['coin'], amount=-fee, time=tx['ts'],
        event_type='unknown', event_id=tx['id'], subaccount='spot',
      ))
  for tx in futures:
    out.append(UnknownObservation(
      id=tx['id'], asset=tx['marginCoin'], amount=Decimal(tx['amount']), time=tx['ts'],
      subaccount='futures',
    ))
    if (fee := abs(Decimal(tx['fee']))) > 0:
      out.append(FeeLeg(
        id=f'{tx["id"]}:fee', asset=tx['marginCoin'], amount=-fee, time=tx['ts'],
        event_type='unknown', event_id=tx['id'], subaccount='futures',
      ))
  for margin_type, records in (('crossed', crossed), ('isolated', isolated)):
    subaccount = f'{margin_type}_margin'
    for tx in records:
      out.append(UnknownObservation(
        id=tx['id'], asset=tx['coin'], amount=tx['amount'], time=tx['ts'],
        subaccount=subaccount,
      ))
      if (fee := abs(tx['fee'])) > 0:
        out.append(FeeLeg(
          id=f'{tx["id"]}:fee', asset=tx['coin'], amount=-fee, time=tx['ts'],
          event_type='unknown', event_id=tx['id'], subaccount=subaccount,
        ))
  return out

# Tax endpoints cap the window at 30 days -- reusing the same 30-day range as deposits/withdrawals above.
await flows(deposits_start, deposits_end)


# %% [markdown]
# ### `history(start=None, end=None)`

# %%
async def history(start: datetime | None = None, end: datetime | None = None):
  end = end or datetime.now(timezone.utc)
  start = start or end - timedelta(days=1)
  # Sequential, not `asyncio.gather`'d: each of these already issues several requests
  # internally (one per symbol/margin-type), and Bitget's per-key rate limit is easy to
  # trip by fanning all of them out at once.
  groups: list[Sequence[Observation]] = [
    await spot_trades(start, end),
    await futures_trades(start, end),
    await margin_trades('crossed', start, end),
    await margin_trades('isolated', start, end),
    await crypto_deposits(start, end),
    await crypto_withdrawals(start, end),
    await flows(start, end),
  ]
  for group in groups:
    for observation in group:
      yield HistoryRecord(
        observations=[observation],
        provenance={'source': 'api', 'service': 'bitget', 'id': source_id('bitget')},
      )

hist_end = datetime.now(timezone.utc)
hist_start = hist_end - timedelta(hours=24)  # tightest window among the sources above (spot/futures/margin fills)
[record async for record in history(hist_start, hist_end)]


# %% [markdown]
# ### Coverage assessment: `History`
#
# **Partially supported.** Spot/futures/cross-margin/isolated-margin fills and on-chain
# deposits/withdrawals all map cleanly onto their matching `Observation` subtype. The 24h
# window `history()` runs on is empty on this account, so each source was additionally
# re-checked against a window that does hold rows: a spot fill and both margin fill
# variants on 2026-08-28, futures fills on 2026-08-13, an ETH deposit on 2026-08-09 and an
# AVAX withdrawal on 2026-06-14 (whose `fee` is signed negative on the wire -- see the cell
# above). The `flows` overlap is real: that ETH deposit shows up both as a `CryptoDeposit`
# and as an `UnknownObservation` from `tax.spot_records`.
#
# Each source needs its own chunking rule for a window wider than one call allows: `tax.*`
# caps at 30 days per call (and at 500 rows per page -- this account's `tax.spot_records`
# hits that cap on a 30-day window, mostly `batch_interest_user_in` rows, and the notebook
# does not paginate). `spot.order.fills`/`mix.order.fills`/`margin.*.order.fills` document
# no window cap but all use `idLessThan`-style manual pagination beyond one page.
#
# **Not covered here, but present on the venue:**
# - **COIN-FUTURES / USDC-FUTURES** -- `futures_trades` only walks `USDT-FUTURES` for
#   tractability; the other two `productType`s use different symbol universes and would
#   need their own market list. (Both are empty on this account: `tax.futures_records`
#   returns nothing for either.)
# - **P2P and copy trading** -- explicitly out of scope, matching production's own
#   documented exclusions.
# - **Elite/sharkfin/loan Earn events** -- `classic.earn.savings.records` covers
#   subscribe/redeem/interest for the savings family (see `earn/classic.ipynb`); the other
#   three Earn families have their own separate records endpoints, not explored here.

# %% [markdown]
# ## `Snapshots`

# %%
async def spot_balances() -> dict[str, Decimal]:
  raw = await client.classic.spot.account.assets()
  out: dict[str, Decimal] = {}
  for b in raw:
    out[b['coin']] = out.get(b['coin'], Decimal(0)) + b['available'] + b['frozen'] + b['locked']
  return out

await spot_balances()


# %%
async def futures_balances() -> dict[str, Decimal]:
  out: dict[str, Decimal] = {}
  for product_type in PRODUCT_TYPES:
    accounts = await client.classic.mix.account.list(product_type=product_type)
    for a in accounts:
      out[a['marginCoin']] = out.get(a['marginCoin'], Decimal(0)) + Decimal(a['available'])
  return {k: v for k, v in out.items() if v != 0}

await futures_balances()


# %%
async def futures_positions() -> dict[str, Position]:
  out: dict[str, Position] = {}
  for product_type in PRODUCT_TYPES:
    positions = await client.classic.mix.position.list(product_type=product_type)
    for p in positions:
      size = p['total'] if p['holdSide'] == 'long' else -p['total']
      out[p['symbol']] = Position(size=size, avg_price=p['openPriceAvg'])
  return out

await futures_positions()


# %%
async def margin_balances(margin_type: str) -> dict[str, Decimal]:
  fn = (
    client.classic.margin.cross.account.assets
    if margin_type == 'crossed'
    else client.classic.margin.isolated.account.assets
  )
  raw = await fn()
  out: dict[str, Decimal] = {}
  for b in raw:
    out[b['coin']] = out.get(b['coin'], Decimal(0)) + b['net']
  return out

await margin_balances('crossed')


# %%
async def earn_balances() -> dict[str, Decimal]:
  raw = await client.classic.earn.account_assets()
  return {b['coin']: Decimal(b['amount']) for b in raw}

await earn_balances()


# %%
async def funding_balances() -> dict[str, Decimal]:
  raw = await client.classic.common.funding_assets()
  return {b['coin']: b['available'] + b['frozen'] for b in raw}

await funding_balances()


# %%
async def bot_balances(account_type: Literal['futures', 'spot']) -> dict[str, Decimal]:
  raw = await client.classic.common.bot_assets(account_type=account_type)
  out: dict[str, Decimal] = {}
  for b in raw:
    equity = Decimal(b['equity'])
    total = equity if equity else Decimal(b['available']) + Decimal(b['frozen'])
    out[b['coin']] = out.get(b['coin'], Decimal(0)) + total
  return out

await bot_balances('spot')


# %% [markdown]
# ### `snapshot(assets=None)`

# %%
async def snapshot(assets: list[str] | None = None) -> SnapshotRecord:
  # Split into two `asyncio.gather`s of <= 6 args: `asyncio.gather`'s typeshed stub only
  # has precise per-position overloads up to 6 arguments -- beyond that it falls back to
  # a homogeneous `list[T]` overload with `T` collapsed to the union of every argument's
  # return type, which defeats the tuple-unpacking below. Both inner `gather` calls still
  # schedule all of their coroutines immediately, so this keeps all 9 calls concurrent.
  (
    spot, futures, positions, crossed_margin, isolated_margin,
  ), (
    earn, funding, spot_bot, futures_bot,
  ) = await asyncio.gather(
    asyncio.gather(
      spot_balances(),
      futures_balances(),
      futures_positions(),
      margin_balances('crossed'),
      margin_balances('isolated'),
    ),
    asyncio.gather(
      earn_balances(),
      funding_balances(),
      bot_balances('spot'),
      bot_balances('futures'),
    ),
  )
  return SnapshotRecord(
    snapshot=Snapshot(subaccounts=[
      SubaccountSnapshot(subaccount='spot', balances=spot),
      SubaccountSnapshot(subaccount='futures', balances=futures, positions=positions),
      SubaccountSnapshot(subaccount='crossed_margin', balances=crossed_margin),
      SubaccountSnapshot(subaccount='isolated_margin', balances=isolated_margin),
      SubaccountSnapshot(subaccount='earn', balances=earn),
      SubaccountSnapshot(subaccount='funding', balances=funding),
      SubaccountSnapshot(subaccount='spot_bot', balances=spot_bot),
      SubaccountSnapshot(subaccount='futures_bot', balances=futures_bot),
    ]),
    provenance={'source': 'api', 'service': 'bitget', 'id': source_id('bitget')},
  )

await snapshot()

# %% [markdown]
# ### Coverage assessment: `Snapshots`
#
# **Fully supported** across the 8 compartments Classic actually separates balances into
# (spot, futures, cross margin, isolated margin, Earn, funding, spot bot, futures bot) --
# all live-tested above, and all small: spot holds dust in five coins, futures 0.0042 USDT,
# cross margin 1.01 USDT, isolated margin 1.51 USDT, Earn 2.31 USDT, funding all zeros, and
# **both bot compartments return an empty list**, so `bot_balances`'s preference for the source's own
# `equity` field over `available + frozen` (`equity` being documented as "0 unless the bot
# has an open position") is written but not exercised -- there is no bot on this account to
# exercise it against. P2P and copy-trading balances are not covered, matching the same
# exclusion `History` documents above.
#
# `classic.mix.account.list` validates for all three product types: the union-margin
# fields (`assetList`, `unionTotalMargin`, `unionAvailable`, `unionMm`) that COIN-FUTURES
# and USDC-FUTURES rows omit are declared `NotRequired`.

# %% [markdown]
# ## Withdraw / place orders (state-mutating -- not shown here)
#
# See `wallet/classic.ipynb` for the withdrawal mapping and `market/classic.ipynb` for
# order placement -- neither is part of the `Reporting` interface, so they aren't
# duplicated in this notebook.
