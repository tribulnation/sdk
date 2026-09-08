# %%
import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os

from dotenv import load_dotenv

from typed_mexc import MEXC
from typed_mexc.core import ApiError

from tribulnation.sdk.reporting import (
  CryptoDeposit,
  CryptoWithdrawal,
  Fee,
  Funding,
  HistoryRecord,
  Position,
  Snapshot,
  SnapshotRecord,
  SpotTrade,
  SubaccountSnapshot,
  source_id,
)

load_dotenv()

client = await MEXC.new(
  api_key=os.environ['MEXC_API_KEY'],
  api_secret=os.environ['MEXC_API_SECRET'],
).__aenter__()

SPOT_MARKETS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']
PERP_MARKETS = ['BTC_USDT', 'ETH_USDT', 'SOL_USDT']
ASSETS = ['BTC', 'ETH', 'USDT']


# %% [markdown]
# ## `History`
#
# MEXC has no single unified activity feed comparable to KuCoin's `account.ledgers` --
# each source below maps a *structured* endpoint directly to its matching `Observation`,
# one call per market/symbol since none of the account-trade/deposit/withdrawal endpoints
# take a list of symbols. All four sources are signed requests
# (`meta={'signed': True}`), needing the same spot/futures account scopes `market.ipynb`/`wallet.ipynb` already found blocked on
# this API key -- shown live below (the failures are real, not fabricated).

# %%
async def spot_trades(start: datetime, end: datetime) -> list[SpotTrade]:
  out: list[SpotTrade] = []
  for symbol in SPOT_MARKETS:
    info = await client.spot.http.market.exchange_info(symbol=symbol)
    base, quote = info['symbols'][0]['baseAsset'], info['symbols'][0]['quoteAsset']
    raw = await client.spot.http.account.trades(
      symbol=symbol, start_time=start, end_time=end
    )
    for t in raw:
      qty = Decimal(t['qty'])
      commission = Decimal(t['commission'])
      out.append(
        SpotTrade(
          id=str(t['id']),
          time=t['time'],
          base=base,
          quote=quote,
          pair=symbol,
          size=qty if t['isBuyer'] else -qty,
          price=Decimal(t['price']),
          order_id=str(t['orderId']),
          fee=Fee(amount=commission, asset=t['commissionAsset'])
          if commission
          else None,
        )
      )
  return out


end = datetime.now(timezone.utc)
start = end - timedelta(hours=24)
try:
  spot_trades_result = await spot_trades(start, end)
except ApiError as e:
  spot_trades_result = e
spot_trades_result


# %%
async def crypto_deposits(start: datetime, end: datetime) -> list[CryptoDeposit]:
  # DepositHistoryItem has no dedicated id field -- txId doubles as the identifier, same
  # as this notebook's Snapshots section falls back to when nothing better is available.
  raw = await client.spot.http.wallet.deposit_history(
    start_time=start,
    end_time=end,
    status='5',  # 5 = SUCCESS
  )
  out: list[CryptoDeposit] = []
  for d in raw:
    if d['coin'] is None:
      continue
    amount = Decimal(d['amount']) if d['amount'] is not None else Decimal(0)
    out.append(
      CryptoDeposit(
        id=d['txId'],
        time=d['insertTime'],
        asset=d['coin'],
        amount=amount,
        network=d['network'],
        tx_id=d['txId'],
        dst_address=d['address'],
        fee=None,  # MEXC's deposit-history endpoint reports no deposit-fee field
      )
    )
  return out


end = datetime.now(timezone.utc)
start = end - timedelta(days=30)
try:
  crypto_deposits_result = await crypto_deposits(start, end)
except ApiError as e:
  crypto_deposits_result = e
crypto_deposits_result


# %%
async def crypto_withdrawals(start: datetime, end: datetime) -> list[CryptoWithdrawal]:
  raw = await client.spot.http.wallet.withdraw_history(
    start_time=start,
    end_time=end,
    status='7',  # 7 = SUCCESS
  )
  out: list[CryptoWithdrawal] = []
  for w in raw:
    if w['coin'] is None:
      continue
    amount = Decimal(w['amount']) if w['amount'] is not None else Decimal(0)
    fee_amount = (
      Decimal(w['transactionFee']) if w['transactionFee'] is not None else Decimal(0)
    )
    out.append(
      CryptoWithdrawal(
        id=w['id'],
        time=w['applyTime'],
        asset=w['coin'],
        amount=-amount,
        network=w['network'],
        tx_id=w['txId'],
        dst_address=w['address'],
        fee=Fee(amount=fee_amount, asset=w['coin']) if fee_amount else None,
      )
    )
  return out


end = datetime.now(timezone.utc)
start = end - timedelta(days=30)
try:
  crypto_withdrawals_result = await crypto_withdrawals(start, end)
except ApiError as e:
  crypto_withdrawals_result = e
crypto_withdrawals_result


# %%
async def funding(start: datetime, end: datetime) -> list[Funding]:
  # `funding_records` reports no settlement-currency field -- looked up per symbol from
  # `contract_info` and cached, since it's constant per contract.
  out: list[Funding] = []
  for symbol in PERP_MARKETS:
    contract = await client.futures.http.market.contract_info(symbol=symbol)
    spec = contract.get('data')
    assert spec is not None and not isinstance(spec, list), (
      f'no contract spec for {symbol}: {contract}'
    )
    page_num = 1
    while True:
      raw = await client.futures.http.account.funding_records(
        symbol=symbol,
        page_num=page_num,
        page_size=100,
      )
      page = raw.get('data')
      assert page is not None, f'no funding records for {symbol}: {raw}'
      stop = False
      for r in page['resultList']:
        time = r['settleTime']
        if time < start:
          stop = True
          break
        if time <= end:
          position_id = r.get('positionId')
          out.append(
            Funding(
              id=str(r['id']),
              time=time,
              # MEXC's own `funding` sign convention here is asserted, not live-verified
              # (blocked by the same futures-read-access scope) -- assumed positive =
              # credited to the balance, matching `SingleAssetObservation.amount`.
              amount=Decimal(str(r['funding'])),
              asset=spec['settleCoin'],
              instrument=symbol,
              position_id=str(position_id) if position_id is not None else None,
            )
          )
      if stop or page_num >= page['totalPage']:
        break
      page_num += 1
  return out


end = datetime.now(timezone.utc)
start = end - timedelta(days=30)
try:
  funding_result = await funding(start, end)
except ApiError as e:
  funding_result = e
funding_result


# %% [markdown]
# ### `history(start=None, end=None)`

# %%
async def history(start: datetime | None = None, end: datetime | None = None):
  end = end or datetime.now(timezone.utc)
  start = start or end - timedelta(days=1)
  groups = await asyncio.gather(
    spot_trades(start, end),
    crypto_deposits(start, end),
    crypto_withdrawals(start, end),
    funding(start, end),
  )
  for group in groups:
    for observation in group:
      yield HistoryRecord(
        observations=[observation],
        provenance={'source': 'api', 'service': 'mexc', 'id': source_id('mexc')},
      )


end = datetime.now(timezone.utc)
start = end - timedelta(days=7)
try:
  history_result = [record async for record in history(start, end)]
except ApiError as e:
  history_result = e
history_result


# %% [markdown]
# ### Coverage assessment: `History`
#
# **Written, blocked live.** All four sources map cleanly onto their matching
# `Observation` subtype -- `spot_trades`/`crypto_deposits`/`crypto_withdrawals` fail live
# with the same `700007 No permission to access the endpoint` error `market.ipynb`/
# `wallet.ipynb` hit on every account-sensitive spot endpoint; `funding` fails live with
# the same `703 Trading information read access is required` futures error. `history()`
# composes all four via `asyncio.gather` (without `return_exceptions=True`), so it
# surfaces the same first `ApiError` live above rather than a partial result -- one
# blocked source fails the whole generator even though, on a differently-scoped key, the
# others might have succeeded independently.
#
# **Not covered here, but present on the venue:**
# - **Margin trading** (`spot` has no dedicated margin-account surface in `typed_mexc` at
#   all, unlike KuCoin's `margin.orders_hf`) -- nothing to map.
# - **Internal transfers** (`spot.http.wallet.internal_transfer_history`,
#   `spot.http.sub_accounts.transfer_history`, `spot.http.wallet.universal_transfer_history`) --
#   would map to `InternalTransfer`/`Transfer`, omitted to keep this demo tractable.
# - **Earn events** -- moot; see `earn.ipynb`, `typed_mexc` has no earn surface at all.
# - **Rebate/affiliate history** (`spot.http.rebate.*`) -- MEXC-specific commission-rebate
#   ledger, no clean `Observation` counterpart, not explored here.
# - **Dust conversion** (`spot.http.wallet.dust_log`/`convert_dust`) -- would map to
#   `Conversion`, omitted to keep this demo tractable.
#
# Two sign-convention caveats, both a direct consequence of the account-scope block making
# live verification impossible: `funding`'s sign (`positive = credited`) and
# `market.ipynb`'s `FundingPayment.amount` (`positive = paid`) are the same underlying
# value read two different ways for two different abstractions -- neither could be
# confirmed against a real settled MEXC funding row here.

# %% [markdown]
# ## `Snapshots`
#
# Split into three supplementary reads (not part of the abstract interface, matching the
# legacy `mexc/poc/reporting.ipynb`'s pattern) so it's clear which piece of `snapshot()` is
# live and which is blocked by this API key's permissions, before composing them.

# %%
async def spot_balances(assets: list[str] | None = None) -> dict[str, Decimal]:
  info = await client.spot.http.account.info()
  out: dict[str, Decimal] = {}
  for b in info['balances']:
    if assets is not None and b['asset'] not in assets:
      continue
    total = Decimal(b['free']) + Decimal(b['locked'])
    if total:
      out[b['asset']] = total
  return out


await spot_balances(assets=ASSETS)


# %%
async def futures_balances(assets: list[str] | None = None) -> dict[str, Decimal]:
  raw = (await client.futures.http.account.assets()).get('data') or []
  out: dict[str, Decimal] = {}
  for a in raw:
    if assets is not None and a['currency'] not in assets:
      continue
    if a['equity']:
      out[a['currency']] = Decimal(str(a['equity']))
  return out


try:
  futures_balances_result = await futures_balances(assets=ASSETS)
except ApiError as e:
  futures_balances_result = e
futures_balances_result


# %%
async def futures_positions() -> dict[str, Position]:
  raw = (await client.futures.http.position.open()).get('data') or []
  out: dict[str, Position] = {}
  for p in raw:
    sign = 1 if p['positionType'] == 1 else -1
    out[p['symbol']] = Position(
      size=sign * Decimal(str(p['holdVol'])),
      avg_price=Decimal(str(p['holdAvgPrice'])),
    )
  return out


try:
  futures_positions_result = await futures_positions()
except ApiError as e:
  futures_positions_result = e
futures_positions_result


# %%
async def snapshot(assets: list[str] | None = None) -> SnapshotRecord:
  spot, futures_bal, futures_pos = await asyncio.gather(
    spot_balances(assets),
    futures_balances(assets),
    futures_positions(),
  )
  return SnapshotRecord(
    snapshot=Snapshot(
      subaccounts=[
        SubaccountSnapshot(subaccount='spot', balances=spot),
        SubaccountSnapshot(
          subaccount='futures', balances=futures_bal, positions=futures_pos
        ),
      ]
    ),
    provenance={'source': 'api', 'service': 'mexc', 'id': source_id('mexc')},
  )


try:
  snapshot_result = await snapshot(assets=ASSETS)
except ApiError as e:
  snapshot_result = e
snapshot_result

# %% [markdown]
# ### Coverage assessment: `Snapshots`
#
# **Partial.** `spot_balances()` is live and complete above. `futures_balances()` and
# `futures_positions()` both fail live with the same MEXC futures permission errors
# `market.ipynb` already found (`701 Please enable API Key read access` /
# `703 Trading information read access is required`) -- a scope this API key doesn't
# have, not a code issue. `snapshot()` composes all three via `asyncio.gather` (without
# `return_exceptions=True`), so it surfaces the same futures `ApiError` live above rather
# than a partial result, exactly like `history()` above and the legacy
# `mexc/poc/reporting.ipynb`'s equivalent notebook -- one blocked futures call fails the
# whole snapshot even though spot succeeded on its own.
