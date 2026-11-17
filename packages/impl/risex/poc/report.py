# %% [markdown]
# # risex `report` PoC
#
# Maps `typed_risex` onto the SDK `report` surface, one method per cell, each executed live. The rules, and how a typed-client issue is reported in `typed-client-issues.md`, are in `.agents/skills/sdk-poc/SKILL.md`.
#
# An account is one address with one USDC collateral balance and its perpetual positions. Every read is public, keyed by the address: the testnet account (`RISEX_TESTNET_ADDRESS`) and a public mainnet trader (24h volume leaderboard), whose snapshot is displayed as counts only.

# %%
from datetime import datetime
from decimal import Decimal
from typing_extensions import AsyncIterable, Collection
import os

from dotenv import load_dotenv
from typed_risex import RISEx

from tribulnation.sdk.reporting import (
  HistoryRecord,
  Position,
  Snapshot,
  SnapshotRecord,
  SubaccountSnapshot,
)

load_dotenv()

client = RISEx.new(network='mainnet', public=True)
testnet = RISEx.new(network='testnet', public=True)
ME = os.environ['RISEX_TESTNET_ADDRESS']
TRADER = '0x7079b5814032C0b02425135F06F32A0084cdf2d2'
"""A public mainnet trader (leaderboard rank 3 on 2026-11-17), with open positions."""
USDC = 'USDC'
WAD = Decimal(10**18)

# %% [markdown]
# ## Surface
#
# What the client exposes. Widen or narrow the filter until every endpoint the mapping below uses is listed here.

# %%
from sdk_dev.surface import surface

print(surface('typed_risex', 'RISEx', grep=r'account\.(balance|positions|cross_margin)|portfolio\.details'))


# %% [markdown]
# ## `snapshot`
#
# One subaccount, labelled by the address: the settled USDC balance (`portfolio.details` `summary.usdc_balance`, without unrealized PnL; equal to `account.balance` of the USDC token) and the open positions by `market_id` from `account.positions_paged` (1e18-scaled, `size` signed). An open position's opening fees and accrued funding stay in its quote amount until the position changes (testnet: a 0.0001 BTC long's `quote_amount` was `-(0.0001 x 63753.9) - 0.001275078`, the fee, while `usdc_balance` was unchanged), so they reach the balance only then. Isolated margin is unobserved, so an isolated position raises.

# %%
async def snapshot(assets: Collection[str] | None = None, on: RISEx = client, account: str = TRADER) -> SnapshotRecord:
  details = await on.portfolio.details(account)
  rows = await on.account.positions_paged(account=account, page_size=100)
  if any(p['margin_mode'] == 1 for p in rows):
    raise NotImplementedError('isolated positions')
  usdc = details['summary']['usdc_balance']
  snap = Snapshot(
    subaccounts=[
      SubaccountSnapshot(
        subaccount=account,
        balances={USDC: usdc} if usdc else {},
        positions={str(p['market_id']): Position(size=Decimal(p['size']) / WAD, avg_price=Decimal(p['avg_entry_price']) / WAD) for p in rows},
      )
    ]
  )
  return SnapshotRecord(snapshot=snap, provenance={'source': 'api', 'service': 'risex', 'id': snap.time.isoformat()})


async with client, testnet:
  mine = await snapshot(on=testnet, account=ME)
  theirs = await snapshot()
{
  'testnet': mine.snapshot.subaccounts[0].balances,
  'mainnet trader': {
    'positions': len(theirs.snapshot.subaccounts[0].positions),
    'usdc > 0': theirs.snapshot.subaccounts[0].balances.get(USDC, Decimal(0)) > 0,
  },
}


# %% [markdown]
# ## `history`
#
# Not supported: the Report history surface is being retired (ADR 0016's snapshot scope), as for Lighter and Nado.

# %%
async def history(start: datetime | None = None, end: datetime | None = None) -> AsyncIterable[HistoryRecord]:
  raise NotImplementedError
  yield


# not executed: not supported
[record async for record in history()]

# %% [markdown]
# ## Coverage
#
# Status is one of `verified` (executed live, real data), `empty` (executed live, nothing to show on this account), `blocked` (a typed-client issue, numbered in `typed-client-issues.md`), `not supported` (the venue has no such data) or `not attempted`.
#
# | method | status | note |
# |---|---|---|
# | `snapshot` | verified | testnet balance; mainnet trader's positions |
# | `history` | not supported | Report history is out of scope |

# %% [markdown]
# ## Catalogue
#
# Every ID the verified methods returned, minus what the catalogue translates for this platform. Anything listed is a catalogue addition to make, not something to rename here: the SDK emits venue-native IDs and the catalogue maps them.

# %%
from sdk_dev.catalogue import Ids, gap, load_catalogue

ids = Ids()
for record in (mine, theirs):
  for sub in record.snapshot.subaccounts:
    ids.merge(Ids(assets=set(sub.balances), positions=set(sub.positions)))
missing = gap('risex', ids, load_catalogue())
{'assets': missing.assets, 'positions': len(missing.positions)}
