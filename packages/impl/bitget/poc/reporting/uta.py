# %%
import asyncio
import os
from decimal import Decimal
from datetime import datetime, timedelta, timezone

from typing_extensions import Literal

from typed_bitget import Bitget
from typed_bitget.uta.market.instruments import Instrument
from dotenv import load_dotenv

from tribulnation.sdk.reporting import (
  CryptoDeposit,
  CryptoWithdrawal,
  Fee,
  FeeLeg,
  FutureTrade,
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
  access_key=os.environ['BITGET_UTA_ACCESS_KEY'],
  secret_key=os.environ['BITGET_UTA_SECRET_KEY'],
  passphrase=os.environ['BITGET_UTA_PASSPHRASE'],
).__aenter__()

Category = Literal['SPOT', 'MARGIN', 'USDT-FUTURES', 'COIN-FUTURES', 'USDC-FUTURES']
FuturesCategory = Literal['USDT-FUTURES', 'COIN-FUTURES', 'USDC-FUTURES']
CATEGORIES: list[Category] = ['SPOT', 'MARGIN', 'USDT-FUTURES', 'COIN-FUTURES', 'USDC-FUTURES']
FUTURES_CATEGORIES: list[FuturesCategory] = ['USDT-FUTURES', 'COIN-FUTURES', 'USDC-FUTURES']

instrument_cache: dict[str, Instrument | dict[str, str]] = {}


async def base_quote(symbol: str, category: Category) -> tuple[str | None, str | None]:
  # `Fill`/`FinancialRecord` only carry the raw `symbol` string -- `market.instruments`
  # is the lookup for its base/quote coin split.
  if symbol not in instrument_cache:
    rows = await client.uta.market.instruments(category=category, symbol=symbol)
    instrument_cache[symbol] = rows[0] if rows else {}
  row = instrument_cache[symbol]
  return row.get('baseCoin'), row.get('quoteCoin')


# %% [markdown]
# ## `History`
#
# UTA merges spot/margin/futures fills behind one endpoint (`trade.order.fills`, keyed by
# `category`) and one general ledger (`account.financial_records`, also keyed by
# `category`) -- a much flatter surface than Classic's per-product-line endpoints. This
# notebook maps fills to `SpotTrade` (category `SPOT`/`MARGIN`) or `FutureTrade` (the three
# `*-FUTURES` categories), financial records to `UnknownObservation`+`FeeLeg` (its `type`
# field is an open-ended business-type string, same caveat as Classic's `tax` records), and
# `transfers.deposit`/`withdraw.records` to `CryptoDeposit`/`CryptoWithdrawal`.

# %%
async def trades(category: Category, start: datetime, end: datetime) -> list[Observation]:
  raw = await client.uta.trade.order.fills(category=category, start_time=start, end_time=end)
  fills = raw['list'] or []
  out: list[Observation] = []
  for f in fills:
    qty = Decimal(f['execQty'])
    price = Decimal(f['execPrice'])
    size = qty if f['side'] == 'buy' else -qty
    fee = None
    if f['feeDetail']:
      fee_amount = sum(abs(Decimal(d['fee'])) for d in f['feeDetail'])
      if fee_amount:
        fee = Fee(amount=fee_amount, asset=f['feeDetail'][0]['feeCoin'])
    if category in ('SPOT', 'MARGIN'):
      base, quote = await base_quote(f['symbol'], category)
      out.append(SpotTrade(
        id=f['execId'], time=f['createdTime'], base=base, quote=quote, pair=f['symbol'],
        size=size, price=price, order_id=f['orderId'], fee=fee,
        subaccount='margin' if category == 'MARGIN' else 'spot',
      ))
    else:
      exec_pnl = f.get('execPnl')
      out.append(FutureTrade(
        id=f['execId'], time=f['createdTime'], instrument=f['symbol'], size=size, price=price,
        realized_pnl=Decimal(exec_pnl) if exec_pnl else None,
        order_id=f['orderId'], fee=fee, subaccount='futures',
      ))
  return out

end = datetime.now(timezone.utc)
start = end - timedelta(hours=24)
{category: await trades(category, start, end) for category in CATEGORIES}


# %%
async def flows(category: Category, start: datetime, end: datetime) -> list[Observation]:
  raw = await client.uta.account.financial_records(category=category, start_time=start, end_time=end)
  records = raw['list'] or []
  out: list[Observation] = []
  subaccount = 'futures' if category.endswith('FUTURES') else category.lower()
  for r in records:
    out.append(UnknownObservation(
      id=r['id'], asset=r['coin'], amount=Decimal(r['amount']), time=r['ts'], subaccount=subaccount,
    ))
    if (fee := abs(Decimal(r['fee'] or '0'))) > 0:
      out.append(FeeLeg(
        id=f'{r["id"]}:fee', asset=r['coin'], amount=-fee, time=r['ts'],
        event_type='unknown', event_id=r['id'], subaccount=subaccount,
      ))
  return out

{category: await flows(category, start, end) for category in CATEGORIES}


# %%
async def crypto_deposits(start: datetime, end: datetime) -> list[CryptoDeposit]:
  raw = await client.uta.transfers.deposit.records(start_time=start, end_time=end)
  return [
    CryptoDeposit(
      id=d['orderId'], time=d['createdTime'], asset=d['coin'], amount=d['size'],
      network=d['chain'], tx_id=d['recordId'], src_address=d.get('fromAddress'),
      dst_address=d.get('toAddress'),
    )
    for d in raw
    if d['dest'] == 'on_chain' and d['status'] == 'success'
  ]

deposits_end = datetime.now(timezone.utc)
deposits_start = deposits_end - timedelta(days=30)
await crypto_deposits(deposits_start, deposits_end)


# %%
async def crypto_withdrawals(start: datetime, end: datetime) -> list[CryptoWithdrawal]:
  raw = await client.uta.transfers.withdraw.records(start_time=start, end_time=end)
  return [
    CryptoWithdrawal(
      id=w['orderId'], time=w['createdTime'], asset=w['coin'], amount=-w['size'],
      network=w['chain'], tx_id=w['recordId'], dst_address=w.get('toAddress'),
      # `fee` arrives signed negative (confirmed live: `-0.00000236` on a BTC
      # withdrawal), while `Fee.amount` is a magnitude.
      fee=Fee(amount=abs(w['fee']), asset=w['coin']) if w.get('fee') else None,
    )
    for w in raw
    if w['dest'] == 'on_chain' and w['status'] == 'success'
  ]

await crypto_withdrawals(deposits_start, deposits_end)


# %% [markdown]
# ### `history(start=None, end=None)`

# %%
async def history(start: datetime | None = None, end: datetime | None = None):
  end = end or datetime.now(timezone.utc)
  start = start or end - timedelta(days=1)
  groups = await asyncio.gather(
    *(trades(category, start, end) for category in CATEGORIES),
    *(flows(category, start, end) for category in CATEGORIES),
    crypto_deposits(start, end),
    crypto_withdrawals(start, end),
  )
  for group in groups:
    for observation in group:
      yield HistoryRecord(
        observations=[observation],
        provenance={'source': 'api', 'service': 'bitget', 'id': source_id('bitget')},
      )

hist_end = datetime.now(timezone.utc)
hist_start = hist_end - timedelta(hours=24)
[record async for record in history(hist_start, hist_end)]


# %% [markdown]
# ### Coverage assessment: `History`
#
# **Partially supported.** Fills (`trade.order.fills`) and financial records
# (`account.financial_records`) both accept the same 5-way `category` split and both
# return real data on this account, though not inside the 24h window `history()` uses:
# widening to 30 days turns up XRP spot fills and a DOGE margin fill (2026-08-28) and
# BTCUSDT futures fills (2026-08-13), each mirrored by its own `ORDER_DEALT_*`/`*_DEAL`
# financial record. `crypto_deposits` picks up one real USDC deposit (2026-08-13);
# `crypto_withdrawals` is empty over 30 days -- the account's real BTC withdrawals are
# older (2026-07-31 and 2026-05-02) and only show up on a wider window.
#
# `financial_records`'s `fee` is signed the *same* way as `amount` -- confirmed against
# fee-bearing rows rather than assumed: all seven found (of types `ORDER_DEALT_IN`,
# `BUY_DEAL` and `SELL_DEAL`) report a negative `fee`, e.g. `-0.0011002`. The
# `abs(...)`+negate pattern above therefore yields the same sign it already had, and
# matches Classic's convention.
#
# Two window limits, both found by probing rather than documented: `financial_records`
# rejects a range wider than 90 days (`00001 startTime and endTime interval cannot be
# greater than 90 days`) and rejects a start time more than roughly 90 days back at all
# (`25200 FinancialQueryParam time range illegal`). So it is *not* the unbounded
# alternative to `uta.tax.records`'s 7-day cap -- it is a 90-day rolling window.
#
# `uta.tax.records(biz_type=..., start_time=..., end_time=...)` also exists and returns
# real (empty) data live -- despite its docstring claiming it "requires a dedicated tax API
# key", the regular UTA credentials used throughout this notebook are accepted (re-checked
# today for `SPOT`, `USDT-FUTURES` and `OTHER`), so that docstring caveat looks stale.
# Not used as a primary source here since `financial_records` covers the same ground with
# a wider per-call window.
#
# **Not covered here, but present on the venue:** P2P and copy trading, matching the same
# exclusion Classic's reporting notebook documents.

# %% [markdown]
# ## `Snapshots`
#
# UTA merges spot/margin/futures collateral into one pool (`account.assets()`), unlike
# Classic's many separate balance compartments -- so this notebook's `Snapshot` has far
# fewer `SubaccountSnapshot`s than `reporting/classic.ipynb`'s.

# %%
async def account_balances() -> dict[str, Decimal]:
  raw = await client.uta.account.assets()
  return {a['coin']: a['balance'] for a in raw['assets']}

await account_balances()


# %%
async def futures_positions() -> dict[str, Position]:
  out: dict[str, Position] = {}
  for category in FUTURES_CATEGORIES:
    raw = await client.uta.position.current_positions(category=category)
    for p in raw['list'] or []:
      total = Decimal(p['total'])
      size = total if p['posSide'] == 'long' else -total
      out[p['symbol']] = Position(size=size, avg_price=Decimal(p['avgPrice']))
  return out

await futures_positions()


# %%
async def earn_balances() -> dict[str, Decimal]:
  raw = await client.uta.earn.elite.assets()
  out: dict[str, Decimal] = {}
  for a in raw['resultList']:
    out[a['productCoin']] = out.get(a['productCoin'], Decimal(0)) + Decimal(a['holdingAmount'])
  return out

await earn_balances()


# %% [markdown]
# ### `snapshot(assets=None)`

# %%
async def snapshot(assets: list[str] | None = None) -> SnapshotRecord:
  balances, positions, earn = await asyncio.gather(
    account_balances(), futures_positions(), earn_balances(),
  )
  return SnapshotRecord(
    snapshot=Snapshot(subaccounts=[
      SubaccountSnapshot(subaccount='account', balances=balances, positions=positions),
      SubaccountSnapshot(subaccount='earn', balances=earn),
    ]),
    provenance={'source': 'api', 'service': 'bitget', 'id': source_id('bitget')},
  )

await snapshot()

# %% [markdown]
# ### Coverage assessment: `Snapshots`
#
# **Fully supported**, and structurally simpler than Classic: `account.assets()` is the
# single richest overall-account endpoint (per-coin balance/equity/available/debt, plus
# account-wide equity/margin-ratio/IMR/MMR not modeled at all by `Snapshot` -- would need a
# venue-specific extension to surface). Positions are read per futures `category` since
# `current_positions` requires it; balances are read once for the whole unified account.
# Earn (Elite) holdings are kept as their own compartment, matching Classic's convention of
# giving Earn its own `SubaccountSnapshot` even though the underlying collateral is
# otherwise unified.
