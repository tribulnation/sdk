# %%
import asyncio
from decimal import Decimal
from datetime import datetime, timedelta, timezone

from typed_kucoin import KuCoin
from dotenv import load_dotenv

from tribulnation.sdk.reporting import (
  CryptoDeposit,
  CryptoWithdrawal,
  Fee,
  Funding,
  FutureTrade,
  HistoryRecord,
  Position,
  Snapshot,
  SnapshotRecord,
  SpotTrade,
  SubaccountSnapshot,
  source_id,
)

load_dotenv()

client = await KuCoin.new().__aenter__()

SPOT_MARKETS = ['BTC-USDT', 'ETH-USDT', 'KCS-USDT']
PERP_MARKETS = ['XBTUSDTM', 'ETHUSDTM', 'KCSUSDTM']


# %% [markdown]
# ## `History`
#
# KuCoin has no single unified activity feed -- `account.ledgers` comes closest (every
# balance-changing event across Spot/Margin/Trade, tagged with a free-text `bizType`), but
# it's capped at a 24h window per call and its `bizType` values aren't a documented closed
# set, so mapping it to precise `Observation` subtypes would mean guessing at business
# codes. This notebook instead maps each *structured* source (trade fills, deposits,
# withdrawals, funding) directly to its matching `Observation`, and covers the gap in the
# coverage note below.

# %%
async def spot_trades(start: datetime, end: datetime) -> list[SpotTrade]:
  out: list[SpotTrade] = []
  for symbol in SPOT_MARKETS:
    base, quote = symbol.split('-')
    page = await client.spot.orders_hf.get_trade_history(
      symbol=symbol, start_at=start, end_at=end
    )
    for f in page['items']:
      size = Decimal(f['size'])
      fee_amount = Decimal(f['fee'])
      out.append(
        SpotTrade(
          id=str(f['tradeId']),
          time=f['createdAt'],
          base=base,
          quote=quote,
          pair=symbol,
          size=size if f['side'] == 'buy' else -size,
          price=Decimal(f['price']),
          order_id=f['orderId'],
          fee=Fee(amount=fee_amount, asset=f['feeCurrency']) if fee_amount else None,
        )
      )
  return out


end = datetime.now(timezone.utc)
start = end - timedelta(hours=24)
await spot_trades(start, end)


# %%
async def future_trades(start: datetime, end: datetime) -> list[FutureTrade]:
  out: list[FutureTrade] = []
  for symbol in PERP_MARKETS:
    page = await client.futures.orders.get_trade_history(
      symbol=symbol, start_at=start, end_at=end
    )
    for f in page['items']:
      size = Decimal(f['size'])
      fee_amount = f['openFeePay'] + f['closeFeePay']
      out.append(
        FutureTrade(
          id=f['tradeId'],
          time=f['tradeTime'],
          instrument=symbol,
          settle=f['feeCurrency'],
          size=size if f['side'] == 'buy' else -size,
          price=f['price'],
          order_id=f['orderId'],
          fee=Fee(amount=fee_amount, asset=f['feeCurrency']) if fee_amount else None,
        )
      )
  return out


end = datetime.now(timezone.utc)
start = end - timedelta(hours=24)
await future_trades(start, end)


# %%
async def crypto_deposits(start: datetime, end: datetime) -> list[CryptoDeposit]:
  page = await client.account.deposit.history(
    start_at=start, end_at=end, status='SUCCESS'
  )
  out: list[CryptoDeposit] = []
  for d in page['items']:
    if d['isInner']:
      continue
    fee_amount = Decimal(d['fee'])
    out.append(
      CryptoDeposit(
        id=d['id'],
        time=d['createdAt'],
        asset=d['currency'],
        amount=Decimal(d['amount']),
        network=d['chain'] or None,
        tx_id=d['walletTxId'],
        dst_address=d['address'] or None,
        fee=Fee(amount=fee_amount, asset=d['currency']) if fee_amount else None,
      )
    )
  return out


end = datetime.now(timezone.utc)
start = end - timedelta(days=30)
await crypto_deposits(start, end)


# %%
async def crypto_withdrawals(start: datetime, end: datetime) -> list[CryptoWithdrawal]:
  page = await client.account.withdrawals.history(
    start_at=start, end_at=end, status='SUCCESS'
  )
  out: list[CryptoWithdrawal] = []
  for w in page['items']:
    if w['isInner']:
      continue
    fee_amount = Decimal(w['fee'])
    out.append(
      CryptoWithdrawal(
        id=w['id'],
        time=w['createdAt'],
        asset=w['currency'],
        amount=-Decimal(w['amount']),
        network=w['chain'] or None,
        tx_id=w['walletTxId'],
        dst_address=w['address'] or None,
        fee=Fee(amount=fee_amount, asset=w['currency']) if fee_amount else None,
      )
    )
  return out


end = datetime.now(timezone.utc)
start = end - timedelta(days=30)
await crypto_withdrawals(start, end)


# %%
async def funding(start: datetime, end: datetime) -> list[Funding]:
  out: list[Funding] = []
  for symbol in PERP_MARKETS:
    page = await client.futures.funding_fees.private_funding_history(
      symbol=symbol, start_at=start, end_at=end
    )
    for f in page['dataList']:
      out.append(
        Funding(
          id=str(f['id']),
          time=f['timePoint'],
          # KuCoin's `funding` is already signed the way `SingleAssetObservation.amount`
          # expects: positive means credited to the balance, negative means debited.
          amount=Decimal(str(f['funding'])),
          asset=f['settleCurrency'],
          instrument=symbol,
        )
      )
  return out


end = datetime.now(timezone.utc)
start = end - timedelta(days=30)
await funding(start, end)


# %% [markdown]
# ### `history(start=None, end=None)`

# %%
async def history(start: datetime | None = None, end: datetime | None = None):
  end = end or datetime.now(timezone.utc)
  start = start or end - timedelta(days=1)
  groups = await asyncio.gather(
    spot_trades(start, end),
    future_trades(start, end),
    crypto_deposits(start, end),
    crypto_withdrawals(start, end),
    funding(start, end),
  )
  for group in groups:
    for observation in group:
      yield HistoryRecord(
        observations=[observation],
        provenance={'source': 'api', 'service': 'kucoin', 'id': source_id('kucoin')},
      )


end = datetime.now(timezone.utc)
start = end - timedelta(
  days=7
)  # the tightest per-call cap among the sources above (futures trade history)
[record async for record in history(start, end)]


# %% [markdown]
# ### Coverage assessment: `History`
#
# **Partially supported.** Spot trades, futures trades, on-chain deposits/withdrawals, and
# futures funding all map cleanly onto their matching `Observation` subtype and are
# live-tested above (empty on this account -- no trading/transfer activity in the queried
# window, confirmed by the raw KuCoin responses, not fabricated). Each source needs its own
# chunking rule for a window wider than what one call allows: spot/futures trade history
# caps at 7 days per call (`get_trade_history`'s own pagination only walks pages *inside*
# one window, so a `PaginatedResponse` implementation must also slide the window itself);
# `futures.funding_fees.private_funding_history` allows up to 6 months total but no more
# than 3 months per call; `account.deposit.history`/`account.withdrawals.history` are not
# documented with a window cap but return few enough rows in practice that this wasn't
# independently confirmed.
#
# **Not covered here, but present on the venue:**
# - **Margin trading** (`margin.orders_hf`, `margin.credit`/`margin.debit` borrow/repay) --
#   would map to `SpotTrade`/`Borrow`/`Repay`, omitted to keep this demo tractable.
# - **Internal transfers** (`account.transfer`, sub-account moves) -- `account.ledgers`
#   covers these via `bizType` values like `TRANSFER`/`SUB_TRANSFER`, but as noted above its
#   `bizType` isn't a documented closed set, so this notebook doesn't attempt to parse it
#   into `InternalTransfer`/`Transfer`.
# - **Earn events** (subscribe/redeem/interest payout) -- `earn.account_holding` reports
#   current holdings, not a dated ledger of individual interest accruals; KuCoin has no
#   earn-specific history endpoint distinct from the generic account ledger.
# - **Convert, VIP lending, affiliate, copy trading** -- each has its own account surface
#   (`client.convert`, `client.vip_lending`, `client.affiliate`, `client.copy_trading`) not
#   explored here.
#
# `account.ledgers`/`account.hf_ledgers`/`account.futures_ledgers` remain a fallback catch-
# all `UnknownObservation` source for anything the structured endpoints above miss, at the
# cost of the 24h-window chunking and the free-text `bizType` parsing noted above -- not
# implemented in this notebook to keep the demonstrated mapping to sources whose semantics
# are actually confirmed.

# %% [markdown]
# ## `Snapshots`

# %%
async def snapshot(assets: list[str] | None = None) -> SnapshotRecord:
  spot_accounts, futures_positions, holdings = await asyncio.gather(
    client.account.spot_accounts(),
    client.futures.positions.get_position_list(),
    client.earn.account_holding(),
  )

  spot_balances: dict[str, Decimal] = {}
  for a in spot_accounts:
    if assets is not None and a['currency'] not in assets:
      continue
    spot_balances[a['currency']] = spot_balances.get(
      a['currency'], Decimal(0)
    ) + Decimal(a['balance'])

  earn_balances: dict[str, Decimal] = {}
  for h in holdings['items']:
    if assets is not None and h['currency'] not in assets:
      continue
    held = Decimal(h['holdAmount']) + Decimal(h['redeemingAmount'])
    earn_balances[h['currency']] = earn_balances.get(h['currency'], Decimal(0)) + held

  positions = {
    p['symbol']: Position(
      size=Decimal(p['currentQty']), avg_price=Decimal(str(p['avgEntryPrice']))
    )
    for p in futures_positions
    if p['isOpen']
  }

  return SnapshotRecord(
    snapshot=Snapshot(
      subaccounts=[
        SubaccountSnapshot(subaccount='spot', balances=spot_balances),
        SubaccountSnapshot(subaccount='futures', positions=positions),
        SubaccountSnapshot(subaccount='earn', balances=earn_balances),
      ]
    ),
    provenance={'source': 'api', 'service': 'kucoin', 'id': source_id('kucoin')},
  )


await snapshot()

# %% [markdown]
# ### Coverage assessment: `Snapshots`
#
# **Partially supported.** Spot (`main`+`trade` accounts combined), Earn holdings, and open
# futures positions are covered above with real balances. Two known gaps:
#
# - **Futures balances**: `account.futures_account` (`GET /api/v1/account-overview`)
#   returns a live `404` on this account regardless of currency -- `market.ipynb`'s
#   coverage note traces this to the API key's granted permission scopes (confirmed live
#   via the read-only `account.api_key_info`) missing `Futures`, which KuCoin's docs list
#   as required for this endpoint specifically, while `futures.positions.get_position_list`
#   (used below, and which *does* work) only needs `General`. Not, as first guessed, an
#   unactivated futures wallet. The `futures` subaccount above therefore only carries
#   `positions`, not a settlement-currency balance.
# - **Margin/isolated-margin balances**: `account.spot_accounts()` returns legacy
#   `margin`/`isolated` account-type rows verbatim (confirmed live: this account has a
#   zero-balance `margin` row), but this notebook folds every row into one `spot`
#   subaccount rather than splitting them out, since none of them carry a balance on this
#   account to verify the mapping against.
