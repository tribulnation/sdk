# %% [markdown]
# # evedex `report` PoC
#
# Maps `typed_evedex` onto the SDK `report` surface, one method per cell, each executed live. The rules, and how a typed-client issue is reported in `typed-client-issues.md`, are in `.agents/skills/sdk-poc/SKILL.md`.
#
# An EVEDEX account holds two balances: the **trading balance** (`exchange.account.funding`) that positions are margined against, and the **smart-account wallet** that deposits reach first (`exchange.account.balance`, or the Auth service's `auth.user.balance`). Both are read on prod with the owner's API key alone: the wallet key is dropped from the environment first, since `typed-evedex` would otherwise pick it up.

# %%
from contextlib import AsyncExitStack
from datetime import datetime
from typing_extensions import AsyncIterable, Collection
import os
import warnings

from dotenv import load_dotenv
from typed_evedex import Evedex

from tribulnation.sdk.reporting import HistoryRecord, Position, Snapshot, SnapshotRecord, SubaccountSnapshot

load_dotenv()
os.environ.pop('EVEDEX_PRIVATE_KEY', None)

stack = AsyncExitStack()
client = await stack.enter_async_context(Evedex.new(env='prod', api_key=os.environ['EVEDEX_API_KEY']))
"""Prod, with the API key alone."""
assert client.credentials is not None and client.credentials.account is None

# %% [markdown]
# ## Surface
#
# What the client exposes. Widen or narrow the filter until every endpoint the mapping below uses is listed here.

# %%
from sdk_dev.surface import surface

print(surface('typed_evedex', 'Evedex', grep=r'account\.(funding|balance)$|user\.balance|positions\.list'))


# %% [markdown]
# ## `snapshot`
#
# `trading`: `exchange.account.funding` (per coin, the trading balance without unrealized PnL) and the open positions of `exchange.positions.list` (non-zero `quantity`, signed by `side`, at `avgPrice`). `wallet`: `exchange.account.balance`, the smart-account wallet, deprecated upstream in favour of `auth.user.balance`, which needs the wallet's session; both read the same `1.875744` USDT on 2026-11-19, which the trading balance does not include. Coins are the venue's (`usdt`).

# %%
async def snapshot(assets: Collection[str] | None = None) -> SnapshotRecord:
  trading = await client.exchange.account.funding()
  with warnings.catch_warnings():
    warnings.simplefilter('ignore', DeprecationWarning)
    wallet = await client.exchange.account.balance()
  positions = (await client.exchange.positions.list())['list']
  snap = Snapshot(
    subaccounts=[
      SubaccountSnapshot(
        subaccount='trading',
        balances={b['coin']: b['quantity'] for b in trading if b['quantity']},
        positions={
          p['instrument']: Position(size=-p['quantity'] if p['side'] == 'SELL' else p['quantity'], avg_price=p['avgPrice'])
          for p in positions
          if p['quantity']
        },
      ),
      SubaccountSnapshot(subaccount='wallet', balances={b['currency']: b['balance'] for b in wallet if b['balance']}),
    ]
  )
  return SnapshotRecord(snapshot=snap, provenance={'source': 'api', 'service': 'evedex', 'id': snap.time.isoformat()})


record = await snapshot()
record.snapshot.subaccounts


# %% [markdown]
# ## `history`
#
# Not supported: the Report history surface is out of SDK scope (ADR 0016).

# %%
async def history(start: datetime | None = None, end: datetime | None = None) -> AsyncIterable[HistoryRecord]:
  raise NotImplementedError('EVEDEX report history is not supported')
  yield


'not supported'

# %% [markdown]
# ## Coverage
#
# Status is one of `verified` (executed live, real data), `empty` (executed live, nothing to show on this account), `blocked` (a typed-client issue, numbered in `typed-client-issues.md`), `not supported` (the venue has no such data) or `not attempted`.
#
# | method | status | note |
# |---|---|---|
# | `snapshot` | verified | prod, API key alone: trading balance and wallet; flat (positions populate during the lifecycle run) |
# | `history` | not supported | Report history is out of scope |

# %% [markdown]
# ## Catalogue
#
# Every ID the verified methods returned, minus what the catalogue translates for this platform. Anything listed is a catalogue addition to make, not something to rename here: the SDK emits venue-native IDs and the catalogue maps them.

# %%
from sdk_dev.catalogue import Ids, gap, load_catalogue

ids = Ids()
for sub in record.snapshot.subaccounts:
  ids.merge(Ids(assets=set(sub.balances), positions=set(sub.positions)))
missing = gap('evedex', ids, load_catalogue())
{'assets': missing.assets, 'positions': missing.positions}

# %% [markdown]
# ## Cleanup

# %%
await stack.aclose()
