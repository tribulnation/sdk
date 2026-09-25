# %% [markdown]
# # aster `report` PoC
#
# Maps `typed_aster` onto the SDK `report` surface, one method per cell; Coverage records what ran on testnet and what remains unmapped. The rules, and how a typed-client issue is reported in `typed-client-issues.md`, are in `.agents/skills/sdk-poc/SKILL.md`.

# %%
from datetime import datetime, timedelta, timezone
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
    grep=r'(spot|futures)\.account\.(info|balance|income|transaction_history)|futures\.position\.risk',
  )
)


# %% [markdown]
# ## `snapshot`
#
# Fetch the current balances and positions of the account.


# %%
async def snapshot(assets: Collection[str] | None = None) -> SnapshotRecord:
  """Avoid an incomplete account snapshot while native spot balances are missing."""
  raise NotImplementedError(
    'Testnet spot account.info omits funded balances; see testnet-issues.md'
  )


try:
  await snapshot()
except NotImplementedError as exc:
  print(str(exc))

# Keep the conflicting native sources visible without emitting a partial Snapshot.
spot = await client.spot.account.info()
futures = await client.futures.account.balance()
spot_transfers = await client.spot.account.transaction_history(
  type='TRANSFER_FUTURE_TO_SPOT'
)
{
  'spot_balances': spot['balances'],
  'spot_transfers': [
    (r['tranId'], r['asset'], r['balanceDelta']) for r in spot_transfers
  ],
  'futures_balances': {r['asset']: r['balance'] for r in futures if r['balance']},
  'futures_positions': [
    (r['symbol'], r['positionAmt'], r['entryPrice'])
    for r in await client.futures.position.risk()
    if r['positionAmt']
  ],
}


# %% [markdown]
# ## `history`
#
# Stream your transaction history as `HistoryRecord`s, each with its `Provenance`.


# %%
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
# Testnet only. Snapshot is blocked by the missing native spot balance view.
# History preserves signed native cash deltas as `UnknownObservation`, with endpoint-scoped
# provenance and the original category in details. It does not classify trades, internal
# transfers, deposits or staking; it is not a complete position ledger.
#
# | method | status | note |
# |---|---|---|
# | `snapshot` | blocked | Spot native balances remain empty despite confirmed funding and fills; testnet-issues.md |
# | `history` | verified | Nonempty native spot/perp cash ledgers; distinct IDs for shared-transaction asset/category legs; unclassified observations |

# %% [markdown]
# ## Catalogue
#
# Every ID the verified methods returned, minus what the catalogue translates for this platform. Anything listed is a catalogue addition to make, not something to rename here: the SDK emits venue-native IDs and the catalogue maps them.

# %%
from sdk_dev.catalogue import Ids, gap, load_catalogue

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
