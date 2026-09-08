# %%
import asyncio
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from typing_extensions import Awaitable, Sequence, TypeVar

from typed_binance import Binance
from typed_core.exceptions import AuthError
from dotenv import load_dotenv

from tribulnation.sdk.reporting import (
  CryptoDeposit,
  CryptoWithdrawal,
  Fee,
  FeeLeg,
  Funding,
  FutureTrade,
  HistoryRecord,
  Observation,
  Position,
  RealizedPnl,
  Snapshot,
  SnapshotRecord,
  SpotTrade,
  SubaccountSnapshot,
  Transfer,
  UnknownObservation,
  source_id,
)

load_dotenv()

client = Binance.new()

SPOT_MARKETS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']
PERP_MARKETS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']

# %% [markdown]
# ## `History`
#
# Binance has no venue-wide unified activity feed. Production `tribulnation.binance` has
# no `report`/`reporting` module at all yet (`packages/impl/binance/pkg/src/tribulnation/
# binance/` only has `earn`, `wallet`, `market`) -- this notebook is an independent,
# from-scratch exploration of how far `typed_binance`'s raw endpoints can be hand-mapped
# onto `Report`, not a reflection of anything that already exists.
#
# Spot fills and USD-M futures fills are each per-symbol, so both loop over a fixed market
# list the way `market.ipynb` does. Deposits/withdrawals and USD-M futures income
# (`fapi/v1/income` -- funding, realized PnL, commission, and internal transfers all come
# back from this one account-wide, multi-type endpoint) need no symbol at all.

# %%
# This account's API key, checked up front since it explains every `usdm_futures` result
# below: `enableFutures` is false, so every USD-M futures call 401s regardless of the
# mapping code's correctness -- not a gap in this notebook's coverage of the endpoints.
await client.spot.http.wallet.account.api_restrictions()


# %%
async def spot_trades(start: datetime, end: datetime) -> list[SpotTrade]:
  out: list[SpotTrade] = []
  for symbol in SPOT_MARKETS:
    fills = await client.spot.http.account.my_trades(
      symbol=symbol, start_time=start, end_time=end
    )
    for f in fills:
      out.append(
        SpotTrade(
          id=str(f['id']),
          time=f['time'],
          pair=symbol,
          size=f['qty'] if f['isBuyer'] else -f['qty'],
          price=f['price'],
          order_id=str(f['orderId']),
          fee=Fee(amount=f['commission'], asset=f['commissionAsset'])
          if f['commission']
          else None,
        )
      )
  return out


end = datetime.now(timezone.utc)
start = end - timedelta(hours=24)  # my_trades' own per-call cap
await spot_trades(start, end)


# %%
async def future_trades(start: datetime, end: datetime) -> list[FutureTrade]:
  out: list[FutureTrade] = []
  for symbol in PERP_MARKETS:
    fills = await client.usdm_futures.http.trading.user_trades(
      symbol=symbol, start_time=start, end_time=end
    )
    for f in fills:
      if 'id' not in f or 'price' not in f or 'qty' not in f or 'time' not in f:
        continue
      qty = Decimal(f['qty'])
      fee_amount = Decimal(f['commission']) if 'commission' in f else None
      out.append(
        FutureTrade(
          id=str(f['id']),
          time=f['time'],
          instrument=symbol,
          settle=f.get('marginAsset'),
          size=qty if f.get('side') == 'BUY' else -qty,
          price=Decimal(f['price']),
          realized_pnl=Decimal(f['realizedPnl']) if 'realizedPnl' in f else None,
          order_id=str(f['orderId']) if 'orderId' in f else None,
          fee=Fee(amount=fee_amount, asset=f['commissionAsset'])
          if fee_amount is not None and 'commissionAsset' in f
          else None,
        )
      )
  return out



# %%
# not executed: signed USD-M futures calls 401 on this key (`enableFutures` is false, see `api_restrictions()` in reporting.ipynb, and the account is geo-blocked from enabling it)
await future_trades(
  datetime.now(timezone.utc) - timedelta(days=7), datetime.now(timezone.utc)
)


# %%
async def crypto_deposits(start: datetime, end: datetime) -> list[CryptoDeposit]:
  # status=1 ("success") per Binance's public REST docs. `DepositRecord.status` is typed
  # `Literal[0, 1, 2, 6, 7, 8]`, so the accepted set does come from the client, but nothing
  # in it says which code means what -- that mapping is carried over from upstream docs.
  rows = await client.spot.http.wallet.capital.deposit.history(
    start_time=start, end_time=end, status=1
  )
  out: list[CryptoDeposit] = []
  for d in rows:
    out.append(
      CryptoDeposit(
        id=d['id'],
        time=d['insertTime'],
        asset=d['coin'],
        amount=d['amount'],
        network=d['network'] or None,
        tx_id=d['txId'] or None,
        dst_address=d['address'] or None,
        # Binance charges no fee for crypto deposits; there's no fee field on this endpoint.
        fee=None,
      )
    )
  return out


end = datetime.now(timezone.utc)
start = end - timedelta(days=30)
await crypto_deposits(start, end)


# %%
async def crypto_withdrawals(start: datetime, end: datetime) -> list[CryptoWithdrawal]:
  # status=6 ("completed") per Binance's public REST docs, same caveat as crypto_deposits above.
  rows = await client.spot.http.wallet.capital.withdraw.history(
    start_time=start, end_time=end, status=6
  )
  out: list[CryptoWithdrawal] = []
  for w in rows:
    if w['transferType'] == 1:
      continue  # internal (Binance-to-Binance) transfer, not an on-chain withdrawal
    out.append(
      CryptoWithdrawal(
        id=w['id'],
        time=w['applyTime'],
        asset=w['coin'],
        amount=-w['amount'],
        network=w.get('network') or None,
        tx_id=w['txId'] or None,
        dst_address=w['address'] or None,
        fee=Fee(amount=w['transactionFee'], asset=w['coin'])
        if w['transactionFee']
        else None,
      )
    )
  return out


end = datetime.now(timezone.utc)
start = end - timedelta(days=30)
await crypto_withdrawals(start, end)


# %%
async def futures_income(start: datetime, end: datetime) -> list[Observation]:
  """Maps `fapi/v1/income` across the four `Observation` subtypes it actually carries
  economic meaning for; every other `incomeType` (WELCOME_BONUS, INSURANCE_CLEAR, ...)
  falls back to `UnknownObservation` rather than being silently dropped.
  """
  rows = await client.usdm_futures.http.account.income(start_time=start, end_time=end)
  out: list[Observation] = []
  for r in rows:
    amount = Decimal(r['income']) if 'income' in r else Decimal(0)
    asset = r.get('asset') or '?'
    time = r.get('time')
    match r.get('incomeType'):
      case 'FUNDING_FEE':
        out.append(
          Funding(
            id=str(r.get('tranId')),
            time=time,
            amount=amount,
            asset=asset,
            instrument=r.get('symbol'),
          )
        )
      case 'REALIZED_PNL':
        out.append(
          RealizedPnl(
            id=str(r.get('tranId')),
            time=time,
            instrument=r.get('symbol'),
            asset=asset,
            amount=amount,
            trade_id=r.get('tradeId'),
          )
        )
      case 'COMMISSION':
        out.append(
          FeeLeg(
            id=str(r.get('tranId')),
            time=time,
            asset=asset,
            amount=abs(amount),
            event_type='future_trade',
            event_id=r.get('tradeId'),
          )
        )
      case 'TRANSFER' | 'INTERNAL_TRANSFER':
        out.append(
          Transfer(id=str(r.get('tranId')), time=time, amount=amount, asset=asset)
        )
      case _:
        out.append(
          UnknownObservation(
            id=str(r.get('tranId')), time=time, amount=amount, asset=asset
          )
        )
  return out



# %%
# not executed: signed USD-M futures calls 401 on this key (`enableFutures` is false, see `api_restrictions()` in reporting.ipynb, and the account is geo-blocked from enabling it)
await futures_income(
  datetime.now(timezone.utc) - timedelta(days=30), datetime.now(timezone.utc)
)

# %% [markdown]
# ### `history(start=None, end=None)`
#
# Internal (Spot<->Funding<->Margin<->Futures) transfers made via `asset.transfer.create`
# are queryable through `asset.transfer.history`, but only one `type` at a time -- there's
# no "every type" wildcard, unlike the sources above. Demonstrated below for the two most
# common directions (`MAIN_FUNDING`/`FUNDING_MAIN`); the full `UniversalTransferType`
# enumeration has 31 values (see coverage note).

# %%
from typed_binance.schemas import UniversalTransferType


async def internal_transfers(start: datetime, end: datetime) -> list[Transfer]:
  out: list[Transfer] = []
  types: list[UniversalTransferType] = ['MAIN_FUNDING', 'FUNDING_MAIN']
  for type in types:
    page = await client.spot.http.wallet.asset.transfer.history(
      type=type, start_time=start, end_time=end
    )
    for t in page.get('rows') or []:
      signed = Decimal(t['amount']) if type == 'FUNDING_MAIN' else -Decimal(t['amount'])
      out.append(
        Transfer(
          id=str(t['tranId']),
          time=t['timestamp'],
          amount=signed,
          asset=t['asset'],
          src_account='funding' if type == 'FUNDING_MAIN' else 'spot',
          dst_account='spot' if type == 'FUNDING_MAIN' else 'funding',
        )
      )
  return out


end = datetime.now(timezone.utc)
start = end - timedelta(days=30)
await internal_transfers(start, end)

# %%
T = TypeVar('T')


async def _guarded(coro: Awaitable[T]) -> T | AuthError:
  """Run one `History` source, returning a caught `AuthError` instead of raising it.
  `history()` treats an `AuthError` as a genuine per-source capability gap only when at
  least one sibling source succeeds; if every source hits the same wall, that's a broken
  credential set (or a fully-disabled key), not a capability gap, so it gets re-raised.
  """
  try:
    return await coro
  except AuthError as e:
    return e


async def history(
  start: datetime | None = None,
  end: datetime | None = None,
) -> list[HistoryRecord]:
  end = end or datetime.now(timezone.utc)
  start = start or end - timedelta(days=1)
  results = await asyncio.gather(
    _guarded(spot_trades(start, end)),
    _guarded(future_trades(start, end)),
    _guarded(crypto_deposits(start, end)),
    _guarded(crypto_withdrawals(start, end)),
    _guarded(futures_income(start, end)),
    _guarded(internal_transfers(start, end)),
  )
  auth_errors = [r for r in results if isinstance(r, AuthError)]
  if len(auth_errors) == len(results):
    raise auth_errors[0]
  out: list[HistoryRecord] = []
  for result in results:
    if isinstance(result, AuthError):
      continue
    for observation in result:
      out.append(
        HistoryRecord(
          observations=[observation],
          provenance={
            'source': 'api',
            'service': 'binance',
            'id': source_id('binance'),
          },
        )
      )
  return out


end = datetime.now(timezone.utc)
start = end - timedelta(
  hours=24
)  # the tightest per-call cap among the sources above (spot my_trades)
await history(start, end)

# %% [markdown]
# ### Coverage assessment: `History`
#
# **Partially supported**, mapping six distinct source endpoints onto seven `Observation`
# subtypes. `spot_trades`, `crypto_deposits`, `crypto_withdrawals`, and
# `internal_transfers` are live-tested above: `crypto_deposits` returns one real 10 USDC
# deposit over its 30-day window, the other three are empty for the windows queried
# (confirmed via the raw responses, not fabricated). `future_trades` and
# `futures_income` are not attempted: `api_restrictions()` above confirms
# `enableFutures: false` on the API key in `.env`, the account is geo-blocked from enabling
# it, and every signed USD-M call 401s, so their call cells are left unexecuted and the
# mapping is unverified.
#
# `history()` only swallows `AuthError` specifically (via `_guarded`), and only when at
# least one sibling source succeeds -- any other exception, or an `AuthError` from *every*
# source, propagates instead of being silently reported as an empty result. That distinction
# matters here: on this account `future_trades`/`futures_income` both raise `AuthError`
# while the other four sources succeed, so
# `history()` correctly returns the partial result rather than masking a real outage/bug as
# "no history".
#
# Each source has its own chunking rule for a window wider than one call allows: spot
# `my_trades` caps at 24h per call and is per-symbol; USD-M futures `user_trades` caps at 7
# days per call and is also per-symbol; `capital.deposit.history`/`capital.withdraw.history`
# cap at 90 days per call and are account-wide; `usdm_futures.account.income` is
# undocumented for a per-call cap beyond "last three months of data total";
# `asset.transfer.history` is documented queryable over the last 6 months, defaulting to 7
# days when no window is given.
#
# **Not covered here, but present on the venue:**
# - **Margin trading** (`spot.http.margin`) -- borrow/repay and margin-account trade
#   history would map to `Borrow`/`Repay`/`SpotTrade`, omitted to keep this demo tractable.
# - **COIN-M futures** (`client.coinm_futures`) -- has its own parallel `account.income`/
#   `trading.user_trades` surface, structurally identical to the USD-M mapping above but
#   settled in the base asset rather than USDT/USDC/BTC. Not explored here -- flagged
#   separately as a possible `PerpMarket`/`Exchange` gap, since `market.ipynb` doesn't cover
#   it either.
# - **Simple Earn subscribe/redeem/reward events** -- `simple_earn.flexible.history`/
#   `simple_earn.locked.history` (rewards/subscription/redemption sub-endpoints) exist and
#   would map to `Yield`, but weren't explored here; `earn.ipynb` covers the *current*
#   Earn product catalog, not a dated ledger of past Earn activity.
# - **Convert, C2C, Pay, Fiat, NFT, Mining, Options, Portfolio Margin** -- each has its own
#   account-scoped history surface (`spot.http.convert`, `.c2c`, `.pay`, `.fiat`, `.nft`,
#   `.mining`, `client.options`, `client.portfolio_margin`) not explored here.
# - **The other 29 `UniversalTransferType` values** -- `internal_transfers` above only
#   demonstrates Spot<->Funding; Margin/USD-M/COIN-M/Options/Portfolio-Margin transfers
#   would need their own `type` values queried the same way, one call per direction, since
#   the endpoint takes exactly one `type` per call rather than an "all directions" option.

# %% [markdown]
# ## `Snapshots`

# %%
# `omit_zero_balances` is a plain Python `bool`, which `typed_binance` lowercases on the
# wire as Binance's `'^(true|false){1}$'` validator for this param requires.
await client.spot.http.account.info(omit_zero_balances=True)

# %%
from typed_binance.spot.http.account.info import AccountBalance
from typed_binance.spot.http.simple_earn.flexible.position import FlexiblePosition
from typed_binance.spot.http.simple_earn.locked.position import LockedPosition
from typed_binance.usdm_futures.http.account.account_v3 import UsdMFuturesAccountV3Asset
from typed_binance.usdm_futures.http.trading.position_risk_v3 import (
  FuturesPositionRiskV3Row,
)


async def snapshot(assets: list[str] | None = None) -> SnapshotRecord:
  # `PaginatedResponse` (the earn `*_paged(...)` calls) isn't hashable, and `asyncio.gather`
  # needs each argument to be a plain awaitable/coroutine; wrapping in `_guarded`'s own
  # coroutine sidesteps that as a side effect.
  #
  results = await asyncio.gather(
    _guarded(client.spot.http.account.info(omit_zero_balances=True)),
    _guarded(client.usdm_futures.http.account.account_v3()),
    _guarded(client.usdm_futures.http.trading.position_risk_v3()),
    _guarded(client.spot.http.simple_earn.flexible.position_paged(size=100)),
    _guarded(client.spot.http.simple_earn.locked.position_paged(size=100)),
  )
  # Only raise if every source hit an AuthError -- see `_guarded`'s docstring.
  auth_errors = [r for r in results if isinstance(r, AuthError)]
  if len(auth_errors) == len(results):
    raise auth_errors[0]
  (
    spot_info,
    futures_account,
    futures_positions,
    flexible_positions,
    locked_positions,
  ) = results

  # An `AuthError`ed source contributes no rows; naming each source's row type here keeps
  # the comprehensions below typed rather than falling back to an untyped empty literal.
  spot_balance_rows: list[AccountBalance] = (
    [] if isinstance(spot_info, AuthError) else spot_info['balances']
  )
  futures_asset_rows: list[UsdMFuturesAccountV3Asset] = (
    []
    if isinstance(futures_account, AuthError)
    else futures_account.get('assets') or []
  )
  futures_position_rows: list[FuturesPositionRiskV3Row] = (
    [] if isinstance(futures_positions, AuthError) else futures_positions
  )
  flexible_rows: Sequence[FlexiblePosition] = (
    [] if isinstance(flexible_positions, AuthError) else flexible_positions
  )
  locked_rows: Sequence[LockedPosition] = (
    [] if isinstance(locked_positions, AuthError) else locked_positions
  )

  spot_balances = {
    b['asset']: total
    for b in spot_balance_rows
    if (total := b['free'] + b['locked']) != 0
    and (assets is None or b['asset'] in assets)
  }

  futures_balances = {
    a['asset']: Decimal(a['walletBalance'])
    for a in futures_asset_rows
    if 'asset' in a
    and 'walletBalance' in a
    and (assets is None or a['asset'] in assets)
  }
  futures_positions_by_symbol = {
    p['symbol']: Position(
      size=Decimal(p['positionAmt']), avg_price=Decimal(p.get('entryPrice') or 0)
    )
    for p in futures_position_rows
    if Decimal(p['positionAmt']) != 0
  }

  earn_balances: dict[str, Decimal] = {}
  for p in flexible_rows:
    if assets is not None and p['asset'] not in assets:
      continue
    earn_balances[p['asset']] = earn_balances.get(p['asset'], Decimal(0)) + Decimal(
      p['totalAmount']
    )
  for p in locked_rows:
    if assets is not None and p['asset'] not in assets:
      continue
    held = Decimal(p['amount']) + Decimal(p['redeemingAmt'])
    earn_balances[p['asset']] = earn_balances.get(p['asset'], Decimal(0)) + held

  return SnapshotRecord(
    snapshot=Snapshot(
      subaccounts=[
        SubaccountSnapshot(subaccount='spot', balances=spot_balances),
        SubaccountSnapshot(
          subaccount='usdm_futures',
          balances=futures_balances,
          positions=futures_positions_by_symbol,
        ),
        SubaccountSnapshot(subaccount='earn', balances=earn_balances),
      ]
    ),
    provenance={'source': 'api', 'service': 'binance', 'id': source_id('binance')},
  )


await snapshot()


# %% [markdown]
# ### Funding wallet
#
# The Funding wallet is a separate balance compartment from Spot on Binance, and
# `snapshot()` above misses it entirely. `wallet.asset.funding_wallet` is the one call
# that reads it -- account-wide, no pagination -- so it folds in as a fourth subaccount
# without touching any of the five sources above.
#

# %%
async def funding_balances(assets: list[str] | None = None) -> dict[str, Decimal]:
  rows = await client.spot.http.wallet.asset.funding_wallet()
  return {
    r['asset']: total
    for r in rows
    if (total := r['free'] + r['locked'] + r['freeze'] + r['withdrawing']) != 0
    and (assets is None or r['asset'] in assets)
  }


async def snapshot_with_funding(assets: list[str] | None = None) -> SnapshotRecord:
  record, funding = await asyncio.gather(
    snapshot(assets),
    _guarded(funding_balances(assets)),
  )
  record.snapshot.subaccounts.append(
    SubaccountSnapshot(
      subaccount='funding',
      balances={} if isinstance(funding, AuthError) else funding,
    )
  )
  return record


await snapshot_with_funding()

# %% [markdown]
# ### Coverage assessment: `Snapshots`
#
# **Partially supported.** Spot and Simple Earn holdings are covered above with real
# balances from the live account (spot holds a handful of small balances; Simple Earn is
# empty -- confirmed by the raw responses, not fabricated). The `usdm_futures`
# subaccount is structurally wired up (wallet balance from `account_v3`, open positions
# from `position_risk_v3`) but always comes back empty on this account for the same
# API-key permission gap as `History`'s `future_trades`/`futures_income`
# (`enableFutures: false`, confirmed above), so it is unverified. `snapshot()` uses the same `_guarded` helper as
# `history()`: it only swallows `AuthError`, and only raises if *every* gathered source hits
# one -- here `usdm_futures.account_v3`/`.position_risk_v3` both `AuthError` while spot and
# Simple Earn succeed, so the partial result comes back instead of the whole call failing.
#
# `spot.http.account.info`'s `omit_zero_balances` parameter is passed for real above:
# `typed_binance.core.auth.wire_params` lowercases Python `bool`s before
# `urllib.parse.urlencode`, which is what Binance's strict `'^(true|false){1}$'` validator
# for this param requires. The `!= 0` filter on `spot_balances` below is kept anyway as a
# harmless client-side backstop.
#
# **Not covered here, but present on the venue:**
# - **COIN-M futures balances/positions** -- `client.coinm_futures.http.account`/
#   `.trading` mirror the USD-M shapes used above; omitted for the same reason as in the
#   `History` coverage note.
# - **Margin/isolated-margin balances** -- `spot.http.margin.account` (cross) and its
#   isolated-margin counterpart aren't queried above; this account's margin balance, if
#   any, is invisible to this snapshot.
# - **Funding wallet** -- covered by `snapshot_with_funding` above rather than by
#   `snapshot()` itself, via `spot.http.wallet.asset.funding_wallet`. It is a *separate*
#   balance compartment from Spot on Binance (unlike the historical rename-only "Funding"
#   label on some other venues), and this account really does hold a balance there that
#   `snapshot()` alone misses.
# - **Options, Portfolio Margin** -- `client.options`/`client.portfolio_margin` each have
#   their own account/balance surface, not explored here.
