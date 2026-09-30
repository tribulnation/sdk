# %% [markdown]
# # aster `report` PoC
#
# Maps `typed_aster` onto the SDK `report` surface, one method per cell; Coverage records what ran on testnet and what remains unmapped. The rules, and how a typed-client issue is reported in `typed-client-issues.md`, are in `.agents/skills/sdk-poc/SKILL.md`.

# %%
from datetime import datetime, timedelta, timezone
import asyncio
from typing_extensions import AsyncIterable, Collection
from dotenv import dotenv_values
from typed_aster import Aster
from sdk_dev.repo import repo_root
from tribulnation.sdk.reporting import (
  SnapshotRecord,
  HistoryRecord,
  UnknownObservation,
)

credentials = dotenv_values(repo_root() / 'packages/impl/aster/poc/.env')
client = await Aster.new(
  mainnet=False,
  public=not bool(credentials.get('ASTER_SIGNER_PRIVATE_KEY')),
  user=credentials.get('ASTER_USER'),
  signer=credentials.get('ASTER_SIGNER_PRIVATE_KEY'),
).__aenter__()

end = datetime.now(timezone.utc)
start = end - timedelta(days=7)

# %% [markdown]
# ## Surface
#
# What the client exposes. Widen or narrow the filter until every endpoint the mapping below uses is listed here.

# %%
from sdk_dev.surface import surface

print(
  surface(
    'typed_aster',
    'Aster',
    grep=r'(spot|futures)\.account\.(info|balance|income|transaction_history)|futures\.position\.risk|chain\.rpc\.get_balance',
  )
)


# %% [markdown]
# ## `snapshot`
#
# Fetch the current balances and positions of the account.
#
# **Mainnet**, signed by the trading agent (`ASTER_USER`, `ASTER_SIGNER_PRIVATE_KEY` in the
# repo's `.env`). Two subaccounts, named as `history` names them: `perp` holds the
# futures wallet balances (`balance`, without unrealized PnL) and the open positions by
# symbol with their `entryPrice`; `spot` holds free plus locked spot balances. The
# address-only `aster_getBalance` RPC reports the same wallets but no entry price; it is
# read beside them as a cross-check.
#
# `staking` is ASTER delegated on Aster Chain, which only Aster's API serves: the RPC's
# staking summary, summing active, pending and unstaking amounts with unclaimed rewards.

# %%
from decimal import Decimal
import os

from dotenv import load_dotenv
from tribulnation.sdk.reporting import Position, Snapshot, SubaccountSnapshot

load_dotenv(repo_root() / '.env')
mainnet = await Aster.new(
  user=os.environ['ASTER_USER'], signer=os.environ['ASTER_SIGNER_PRIVATE_KEY']
).__aenter__()


async def snapshot(assets: Collection[str] | None = None) -> SnapshotRecord:
  """Perp wallet balances and positions, and spot balances."""
  futures, risks, spot, chain = await asyncio.gather(
    mainnet.futures.account.balance(),
    mainnet.futures.position.risk(),
    mainnet.spot.account.info(),
    mainnet.chain.rpc.get_balance(address=os.environ['ASTER_USER']),
  )
  summary = chain.get('staking') or {}
  staked: dict[str, Decimal] = {}
  for amount in (
    summary.get('totalStakedAmount'),
    summary.get('totalPendingStakeAmount'),
    summary.get('totalPendingUnstakeAmount'),
  ):
    if amount:
      staked['ASTER'] = staked.get('ASTER', Decimal(0)) + amount
  for reward in summary.get('totalUnclaimedRewards') or []:
    if reward['amount']:
      staked[reward['asset']] = (
        staked.get(reward['asset'], Decimal(0)) + reward['amount']
      )
  sides: dict[str, list[Position]] = {}
  for r in risks:
    if r['positionAmt']:
      sides.setdefault(r['symbol'], []).append(
        Position(size=r['positionAmt'], avg_price=r['entryPrice'])
      )
  snap = Snapshot(
    subaccounts=[
      SubaccountSnapshot(
        subaccount='perp',
        balances={r['asset']: r['balance'] for r in futures if r['balance']},
        positions={s: Position.merge(p) for s, p in sides.items()},
      ),
      SubaccountSnapshot(
        subaccount='spot',
        balances={
          b['asset']: b['free'] + b['locked']
          for b in spot['balances']
          if b['free'] + b['locked']
        },
      ),
      SubaccountSnapshot(subaccount='staking', balances=staked),
    ]
  )
  return SnapshotRecord(
    snapshot=snap,
    provenance={'source': 'api', 'service': 'aster', 'id': snap.time.isoformat()},
  )


record = await snapshot()
record.snapshot.subaccounts

# %% [markdown]
# Cross-check against the address-only RPC: the same perp and spot wallets, and position
# sizes; `notionalValue - unrealizedProfit` over the size reproduces `entryPrice`.

# %%
rpc = await mainnet.chain.rpc.get_balance(address=os.environ['ASTER_USER'])
{
  'perp': {a['asset']: a['walletBalance'] for a in rpc.get('perpAssets', [])},
  'spot': {a['asset']: a['walletBalance'] for a in rpc.get('spotAssets', [])},
  'positions': [
    (
      p['symbol'],
      p['positionAmount'],
      p.get('notionalValue', Decimal(0)) - p.get('unrealizedProfit', Decimal(0)),
    )
    for group in rpc.get('positions', [])
    for p in group['positions']
  ],
  'staking': rpc.get('staking'),
}


# %% [markdown]
# ## `history`
#
# Stream your transaction history as `HistoryRecord`s, each with its `Provenance`.


# %%
# not executed: testnet history needs `ASTER_*` testnet credentials in packages/impl/aster/poc/.env; verified there before this snapshot work
async def history(
  start: datetime | None = None, end: datetime | None = None
) -> AsyncIterable[HistoryRecord]:
  """Preserve native cash-ledger deltas as unclassified observations, scoped by bucket."""
  upper = end or datetime.now(timezone.utc)
  lower = start or upper - timedelta(days=7)
  if lower.utcoffset() is None or upper.utcoffset() is None or upper < lower:
    raise ValueError('Expected aware, ordered bounds')
  async for page in client.futures.account.income_paged(
    start_time=lower, end_time=upper, limit=1000
  ):
    for row in page:
      identity = f'perp:income:{row["incomeType"]}:{row["tranId"]}'
      yield HistoryRecord(
        observations=[
          UnknownObservation(
            id=str(row['tranId']),
            time=row['time'],
            subaccount='perp',
            asset=row['asset'],
            amount=row['income'],
          )
        ],
        provenance={
          'source': 'api',
          'service': 'aster_testnet',
          'id': identity,
          'details': row,
        },
      )
  async for page in client.spot.account.transaction_history_paged(
    start_time=lower, end_time=upper, limit=1000
  ):
    for entry in page:
      yield HistoryRecord(
        observations=[
          UnknownObservation(
            id=f'{entry["tranId"]}:{entry["type"]}:{entry["asset"]}',
            time=entry['time'],
            subaccount='spot',
            asset=entry['asset'],
            amount=entry['balanceDelta'],
          )
        ],
        provenance={
          'source': 'api',
          'service': 'aster_testnet',
          'id': f'spot:transaction:{entry["tranId"]}:{entry["type"]}:{entry["asset"]}',
          'details': entry,
        },
      )


records = [r async for r in history(start, end)]
assert len({r.provenance['id'] for r in records}) == len(records)
assert records
len(records), records

# %% [markdown]
# ## Coverage
#
# Snapshot ran on mainnet: the signed wallets match the RPC, and `entryPrice` reproduces
# its `notionalValue - unrealizedProfit`. Testnet snapshots stay unsupported: testnet spot
# `account.info` omits funded balances. History ran on testnet only.
# History preserves signed native cash deltas as `UnknownObservation`, with endpoint-scoped
# provenance and the original category in details. It does not classify trades, internal
# transfers, deposits or staking; it is not a complete position ledger.
#
# | method | status | note |
# |---|---|---|
# | `snapshot` | verified | Mainnet: USDC and a negative USDT perp wallet, a FOLKSUSDT long. Spot and staking empty (all staking fields `null`); no public staker was found to populate them |
# | `history` | verified | Nonempty native spot/perp cash ledgers; distinct IDs for shared-transaction asset/category legs; unclassified observations |

# %% [markdown]
# ## Catalogue
#
# Every ID the verified methods returned, minus what the catalogue translates for this platform. Anything listed is a catalogue addition to make, not something to rename here: the SDK emits venue-native IDs and the catalogue maps them.

# %%
from sdk_dev.catalogue import Ids, gap, load_catalogue

record = await snapshot()
gap(
  'aster',
  Ids(assets=set(record.snapshot.balances), positions=set(record.snapshot.positions)),
  load_catalogue(root=repo_root()),
)

# %%
# not executed: testnet history needs `ASTER_*` testnet credentials in packages/impl/aster/poc/.env
records = [r async for r in history(start, end)]
ids = Ids(
  assets={
    o.asset
    for r in records
    for o in r.observations
    if isinstance(o, UnknownObservation)
  }
)
gap('aster', ids, load_catalogue(root=repo_root()))

# %%
await client.__aexit__(None, None, None)  # pyright: ignore[reportUnknownMemberType] -- upstream lifecycle parameters are untyped
await mainnet.__aexit__(None, None, None)  # pyright: ignore[reportUnknownMemberType] -- upstream lifecycle parameters are untyped
