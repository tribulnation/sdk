# %%
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from typed_bybit import Bybit
from dotenv import load_dotenv

from tribulnation.sdk.reporting import (
  HistoryRecord,
  Snapshot,
  SubaccountSnapshot,
  Position,
  SpotTrade,
  Funding,
  CryptoDeposit,
  CryptoWithdrawal,
  Fee,
)
from tribulnation.sdk.reporting.snapshots import SnapshotRecord
from tribulnation.sdk.reporting.models.provenance import ApiProvenance

load_dotenv()

client = await Bybit.new().__aenter__()


# %% [markdown]
# ## `Snapshots.snapshot`

# %%
async def snapshot(assets: list[str] | None = None) -> SnapshotRecord:
  wallet = (await client.account.wallet_balance(account_type='UNIFIED'))['list']
  balances: dict[str, Decimal] = {}
  for account in wallet:
    for coin in account['coin']:
      if assets is not None and coin['coin'] not in assets:
        continue
      # `walletBalance` is required but declared `Literal[''] | Decimal`: a coin the
      # account has never held reports every numeric field as `''`. Compare against
      # `''` rather than testing truthiness, so a real zero balance still records as
      # zero instead of being mistaken for a missing one.
      balance = coin['walletBalance']
      balances[coin['coin']] = balance if balance != '' else Decimal(0)

  perp_positions = (await client.position.list(category='linear', settle_coin='USDT'))[
    'list'
  ]
  positions: dict[str, Position] = {}
  for p in perp_positions:
    if not p['side']:
      continue
    size = Decimal(p['size'])
    positions[p['symbol']] = Position(
      size=size if p['side'] == 'Buy' else -size,
      avg_price=Decimal(p['avgPrice']) if p['avgPrice'] else Decimal(0),
    )

  snap = Snapshot(
    subaccounts=[SubaccountSnapshot(balances=balances, positions=positions)]
  )
  provenance = ApiProvenance(
    id='bybit-uta-snapshot', source='api', service='typed_bybit'
  )
  return SnapshotRecord(snapshot=snap, provenance=provenance)


await snapshot()


# %% [markdown]
# ## `History.history`

# %% [markdown]
# `History.history` is a plain `def` returning an async-iterable directly (not
# `async def`), so it's implemented the same way here: `history()` just returns the
# async generator `_history_records()` produces, without itself being a coroutine.

# %%
async def _history_records(start: datetime | None, end: datetime | None):
  """Yield `HistoryRecord`s for spot trades, linear funding settlements, deposits
  and withdrawals in the window."""

  trades = await client.trade.trade_history(
    category='spot',
    start_time=start,
    end_time=end,
    exec_type='Trade',
  )
  for t in trades['list']:
    qty = Decimal(t['execQty'])
    obs = SpotTrade(
      id=t['execId'],
      time=t['execTime'],
      pair=t['symbol'],
      size=qty if t['side'] == 'Buy' else -qty,
      price=Decimal(t['execPrice']),
      order_id=t['orderId'],
      # `execFee` is required and already a parsed `Decimal`. Don't truthiness-guard
      # it: 40 of the 55 spot fills this account has ever made carry exactly `0`, and
      # a zero fee is not an absent one.
      fee=Fee(amount=t['execFee'], asset=t['feeCurrency']),
    )
    yield HistoryRecord(
      observations=[obs],
      provenance=ApiProvenance(
        id=f'spot-trade-{t["execId"]}', source='api', service='typed_bybit'
      ),
    )

  # Bybit's transaction log caps each window to 7 days -- narrower than deposit/withdrawal
  # records (30 days), so it's the binding constraint on the window callers should pass.
  funding = await client.account.transaction_log(
    category='linear',
    type='SETTLEMENT',
    start_time=start,
    end_time=end,
  )
  for e in funding['list']:
    # `.get('funding')` truthy-checked and then indexed doesn't let pyright narrow
    # away the `NotRequired` key (it only recognizes `'key' in dict`); `'funding'
    # not in e` does. Whether the key is ever actually absent or empty on a
    # `type='SETTLEMENT'` row is unverified: this account has never held a perp
    # position, so `transaction_log` returns no SETTLEMENT row in any window Bybit
    # will serve, and this loop stays empty below.
    if 'funding' not in e or not e['funding']:
      continue
    obs = Funding(
      time=e['transactionTime'],
      amount=Decimal(e['funding']),
      asset=e['currency'],
      instrument=e['symbol'] or None,
    )
    yield HistoryRecord(
      observations=[obs],
      provenance=ApiProvenance(
        id=f'funding-{e["id"]}', source='api', service='typed_bybit'
      ),
    )

  deposits = await client.asset.deposit.record(start_time=start, end_time=end)
  for d in deposits['rows']:
    obs = CryptoDeposit(
      id=d['id'],
      time=d['successAt'],
      amount=Decimal(d['amount']),
      asset=d['coin'],
      network=d['chain'],
      tx_id=d['txID'] or None,
      dst_address=d['toAddress'] or None,
      # `depositFee` is required but declared `Literal[''] | Decimal`, and every
      # deposit this account has ever received carries `''` -- Bybit charges no
      # deposit fee, so there is no amount to report.
      fee=None
      if d['depositFee'] == ''
      else Fee(amount=d['depositFee'], asset=d['coin']),
    )
    yield HistoryRecord(
      observations=[obs],
      provenance=ApiProvenance(
        id=f'deposit-{d["id"]}', source='api', service='typed_bybit'
      ),
    )

  withdrawals = await client.asset.withdraw.record(start_time=start, end_time=end)
  for w in withdrawals['rows']:
    obs = CryptoWithdrawal(
      id=w['withdrawId'],
      time=w['updateTime'],
      amount=Decimal(w['amount']),
      asset=w['coin'],
      network=w['chain'],
      tx_id=w['txID'] or None,
      dst_address=w['toAddress'] or None,
      # `withdrawFee` is a required `str`, present on all 13 withdrawals this account
      # has made -- 10 of them `'0'`, which is a free withdrawal rather than a missing
      # fee, so it is reported as `Fee(0)` rather than guarded away.
      fee=Fee(amount=Decimal(w['withdrawFee']), asset=w['coin']),
    )
    yield HistoryRecord(
      observations=[obs],
      provenance=ApiProvenance(
        id=f'withdrawal-{w["withdrawId"]}', source='api', service='typed_bybit'
      ),
    )


def history(start: datetime | None = None, end: datetime | None = None):
  """Fetch reporting history. Matches `History.history`'s shape: a plain function
  returning an async-iterable, not itself an `async def`."""
  return _history_records(start, end)


# A fixed historical week rather than a rolling one: this account has been idle for
# months, and a recent window returns nothing at all. 2025-07-20..27 is the busiest
# week in its two years of retained history -- 35 spot fills, 5 deposits and 4
# withdrawals -- so every branch above except funding yields real records.
start = datetime(2025, 7, 20, tzinfo=timezone.utc)
end = datetime(2025, 7, 27, tzinfo=timezone.utc)
[record async for record in history(start, end)]

# %% [markdown]
# ### Coverage assessment
#
# **Partially supported.** `snapshot()` executes live and reflects the account fully:
# UTA per-coin balances (`account.wallet_balance`) plus open linear perp positions
# (`position.list`) in one `SubaccountSnapshot` -- Bybit's unified account has no
# separate spot/margin/futures wallets to enumerate as distinct subaccounts, so a
# single `SubaccountSnapshot` is the right shape here (`subaccount=None`). The account
# currently holds one coin and no positions, so the snapshot comes back nearly empty.
#
# `history()` covers spot trades, linear funding settlements, and crypto
# deposits/withdrawals. Three of the four are exercised above against real records:
# the week shown yields 35 spot fills, 5 deposits and 4 withdrawals. The funding
# branch is written but unexercised -- this account has never held a perp position, so
# `account.transaction_log(type='SETTLEMENT')` returns nothing in any window Bybit
# will serve, and the shape of a settlement row here is taken from the client's
# schema rather than from a live response.
#
# Not covered by this POC, though the client exposes the underlying endpoints and
# could be added the same way: linear/inverse/option trade fills and closed PnL
# (`position.closed_pnl`), internal UID-to-UID transfers (`asset.transfer`), Earn
# stake/redeem events, bonus/airdrop credits, and fiat on/off-ramp.
# `account.transaction_log`'s 7-day window cap (vs. 30 days for deposit/withdrawal
# records) is the practical constraint on how wide a single `history()` call can span
# before needing to page by re-calling with a shifted window; Bybit refuses any window
# starting more than two years back outright.
#
