# %% [markdown]
# # lighter `report` PoC
#
# Maps `typed_lighter` onto the SDK `report` surface, one method per cell, each executed live. The rules, and how a typed-client issue is reported in `typed-client-issues.md`, are in `.agents/skills/sdk-poc/SKILL.md`.
#
# Runs against **mainnet**, read-only and credential-free: `account.get` by L1 address
# returns the master account and every sub-account, and pool accounts are public. The
# address comes from `LIGHTER_ADDRESS`. Asset IDs are `asset_id` and position IDs are
# `market_id`, as decimal strings.

# %%
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing_extensions import AsyncIterable, Collection
import asyncio
import os

from dotenv import load_dotenv
from typed_lighter import Lighter
from typed_lighter.api.account.get import DetailedAccount
from sdk_dev.repo import repo_root
from tribulnation.sdk.reporting import (
  HistoryRecord,
  Position,
  Snapshot,
  SnapshotRecord,
  SubaccountSnapshot,
)

load_dotenv(repo_root() / '.env')
ADDRESS = os.environ['LIGHTER_ADDRESS']
USDC = 3
ISOLATED = 1

client = await Lighter.new(public=True).__aenter__()

# %% [markdown]
# ## Surface
#
# What the client exposes. Widen or narrow the filter until every endpoint the mapping below uses is listed here.

# %%
from sdk_dev.surface import surface

print(surface('typed_lighter', 'Lighter', grep=r'api\.account\.(get|pnl)\b'))


# %% [markdown]
# ## `snapshot`
#
# Fetch the current balances and positions of the account.
#
# One subaccount per Lighter account (`<index>`), holding its spot and margin balances
# and its positions. `margin_balance` is collateral without unrealized PnL
# (`cross_asset_value - margin_balance` is the cross positions' PnL); each isolated
# position's `allocated_margin` is USDC held beside it. Classic accounts keep spot USDC
# in `balance` beside the perps collateral in `margin_balance`, so both are summed.
#
# Pool shares (public pools, the LLP and LIT staking) are one subaccount per pool
# (`<index>:pool:<pool>`): the holder's fraction `shares / total_shares` of the pool
# account's holdings, in native assets. A pool's `total_asset_value` is its USDC equity
# (unrealized PnL included), but omits its non-USDC balances, which are added as held.
# LIT in its unstaking lockup is `<index>:unlocking`.
#
# A pool the address operates is listed among its accounts, but its holdings belong to
# every shareholder. Only the operator's shares are the address's (`<pool>:operator`),
# and no account's `shares` lists them.


# %%
def holdings(acct: DetailedAccount) -> dict[str, Decimal]:
  """Spot and margin balances, plus the margin allocated to isolated positions."""
  balances = {
    str(a['asset_id']): a['balance'] + a['margin_balance'] for a in acct['assets']
  }
  isolated = sum(
    (p['allocated_margin'] for p in acct['positions'] if p['margin_mode'] == ISOLATED),
    Decimal(0),
  )
  balances[str(USDC)] = balances.get(str(USDC), Decimal(0)) + isolated
  return {asset: qty for asset, qty in balances.items() if qty}


def positions(acct: DetailedAccount) -> dict[str, Position]:
  """Open positions, signed, with their average entry."""
  return {
    str(p['market_id']): Position(
      size=p['sign'] * p['position'], avg_price=p['avg_entry_price']
    )
    for p in acct['positions']
    if p['position']
  }


def pool_claim(pool: DetailedAccount, shares: int) -> dict[str, Decimal]:
  """The holder's pro-rata part of a pool: its USDC equity and every other balance."""
  info = pool.get('pool_info')
  if info is None:
    raise ValueError(f'Account {pool["index"]} is not a pool')
  fraction = Decimal(shares) / Decimal(info['total_shares'])
  held = {
    str(a['asset_id']): a['balance']
    + (a['margin_balance'] if a['asset_id'] != USDC else 0)
    for a in pool['assets']
  }
  held[str(USDC)] = held.get(str(USDC), Decimal(0)) + pool['total_asset_value']
  return {asset: fraction * qty for asset, qty in held.items() if qty}


async def account(index: int) -> DetailedAccount:
  """One account by index."""
  return (await client.api.account.get({'by': 'index', 'value': index}))['accounts'][0]


async def snapshot(assets: Collection[str] | None = None) -> SnapshotRecord:
  """Every account of the address, and its pool shares."""
  accounts = (await client.api.account.get({'by': 'l1_address', 'value': ADDRESS}))[
    'accounts'
  ]
  pool_ids = sorted({s['public_pool_index'] for a in accounts for s in a['shares']})
  pools = dict(zip(pool_ids, await asyncio.gather(*map(account, pool_ids))))
  subaccounts: list[SubaccountSnapshot] = []
  for acct in accounts:
    index = acct['index']
    if (info := acct.get('pool_info')) is not None:
      subaccounts.append(
        SubaccountSnapshot(
          subaccount=f'{index}:operator',
          balances=pool_claim(acct, info['operator_shares']),
        )
      )
      continue
    subaccounts.append(
      SubaccountSnapshot(
        subaccount=str(index), balances=holdings(acct), positions=positions(acct)
      )
    )
    for share in acct['shares']:
      pool = share['public_pool_index']
      subaccounts.append(
        SubaccountSnapshot(
          subaccount=f'{index}:pool:{pool}',
          balances=pool_claim(pools[pool], share['shares_amount']),
        )
      )
    unlocking: dict[str, Decimal] = {}
    for unlock in acct['pending_unlocks']:
      if 'asset_index' in unlock and 'amount' in unlock:
        asset = str(unlock['asset_index'])
        unlocking[asset] = unlocking.get(asset, Decimal(0)) + unlock['amount']
    if unlocking:
      subaccounts.append(
        SubaccountSnapshot(subaccount=f'{index}:unlocking', balances=unlocking)
      )
  snap = Snapshot(subaccounts=subaccounts)
  return SnapshotRecord(
    snapshot=snap,
    provenance={'source': 'api', 'service': 'lighter', 'id': snap.time.isoformat()},
  )


record = await snapshot()
record.snapshot.subaccounts

# %% [markdown]
# Reconcile each account with the venue's own total: `total_asset_value` is margin
# collateral plus isolated equity plus unrealized PnL, so it equals the USDC balance
# minus spot USDC plus the positions' unrealized PnL.

# %%
accounts = (await client.api.account.get({'by': 'l1_address', 'value': ADDRESS}))[
  'accounts'
]
[
  (
    a['index'],
    a['total_asset_value'],
    holdings(a).get(str(USDC), Decimal(0))
    - next((x['balance'] for x in a['assets'] if x['asset_id'] == USDC), Decimal(0))
    + sum((p['unrealized_pnl'] for p in a['positions']), Decimal(0)),
  )
  for a in accounts
]

# %% [markdown]
# Pool valuation, on a public account that holds LLP and LIT staking shares (the test
# address holds none): the LLP claim priced at spot matches the USDC value implied by
# the venue's PnL chart (`pool_inflow - pool_outflow + pool_pnl`).

# %%
HOLDER, LLP = 1060, 281474976710654
holder, llp = await asyncio.gather(account(HOLDER), account(LLP))
shares = next(
  s['shares_amount'] for s in holder['shares'] if s['public_pool_index'] == LLP
)
claim = pool_claim(llp, shares)
details = await client.api.markets.order_book_details()
prices = {
  str(d['base_asset_id']): Decimal(str(d['last_trade_price']))
  for d in details['spot_order_book_details'] or []
  if d['quote_asset_id'] == USDC
}
now = datetime.now(timezone.utc)
chart = await client.api.account.pnl(
  value=HOLDER,
  resolution='1h',
  start_timestamp=now - timedelta(hours=2),
  end_timestamp=now,
  count_back=1,
)
live = chart['pnl'][-1]
(
  claim,
  sum(
    (
      qty * prices.get(asset, Decimal(1 if asset == str(USDC) else 0))
      for asset, qty in claim.items()
    ),
    Decimal(0),
  ),
  live['pool_inflow'] - live['pool_outflow'] + live['pool_pnl'],
)


# %% [markdown]
# An operator: account 72162's address operates pool 281474976694250 and holds operator
# shares in it, which its own `shares` omit. The snapshot claims only those.

# %%
operator = await account(72162)
operated = await account(281474976694250)
info = operated.get('pool_info')
assert info is not None
(
  [s['public_pool_index'] for s in operator['shares']],
  info['operator_shares'],
  info['total_shares'],
  pool_claim(operated, info['operator_shares']),
  operated['total_asset_value'],
)


# %% [markdown]
# ## `history`
#
# Stream your transaction history as `HistoryRecord`s, each with its `Provenance`.


# %%
async def history(
  start: datetime | None = None, end: datetime | None = None
) -> AsyncIterable[HistoryRecord]:
  """Not mapped: `history()` is being retired from the Report surface."""
  raise NotImplementedError('Lighter report history is not supported')
  yield


try:
  [record async for record in history()]
except NotImplementedError as exc:
  print(exc)

# %% [markdown]
# ## Coverage
#
# Status is one of `verified` (executed live, real data), `empty` (executed live, nothing to show on this account), `blocked` (a typed-client issue, numbered in `typed-client-issues.md`), `not supported` (the venue has no such data) or `not attempted`.
#
# | method | status | note |
# |---|---|---|
# | `snapshot` | verified | Mainnet: USDC collateral, an isolated FOLKS short; reconciles with `total_asset_value`. Pool claims checked on a public holder against the PnL chart, and an operator's claim on its own pool |
# | `history` | not attempted | The Report history surface is being retired |

# %% [markdown]
# ## Catalogue
#
# Every ID the verified methods returned, minus what the catalogue translates for this platform. Anything listed is a catalogue addition to make, not something to rename here: the SDK emits venue-native IDs and the catalogue maps them.

# %%
from sdk_dev.catalogue import Ids, gap, load_catalogue

record = await snapshot()
ids = Ids(
  assets=set(record.snapshot.balances), positions=set(record.snapshot.positions)
)
gap('lighter', ids, load_catalogue(root=repo_root()))

# %%
await client.__aexit__(None, None, None)  # pyright: ignore[reportUnknownMemberType] -- upstream lifecycle parameters are untyped
