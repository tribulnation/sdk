# %% [markdown]
# # margin-trade `report` PoC
#
# Maps `typed_margin_trade` onto the SDK `report` surface, one method per cell, each executed live. The rules, and how a typed-client issue is reported in `typed-client-issues.md`, are in `.agents/skills/sdk-poc/SKILL.md`.
#
# Every read is by address and unsigned. The testnet account (`MARGIN_TRADE_TESTNET_ADDRESS`, repo-root `.env`) has perp fills, a funding row, faucet credits, perp/spot transfers and one withdrawal; the mainnet leaderboard accounts `PERP_TRADER` and `SPOT_TRADER` are read through a credential-free client for real funding, spot fills and on-chain deposits. The lifecycle cell opens and closes a 0.001 BTC testnet position with the agent key to compare the snapshot's perp balance against the venue's own `perpBalance`.

# %%
import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing_extensions import Any, AsyncIterator, Collection

from dotenv import dotenv_values
from sdk_dev.repo import repo_root
from typed_margin_trade import MarginTrade
from typed_margin_trade.schemas import Fill
from typed_margin_trade.info.user_funding import UserFundingRecord
from typed_margin_trade.user.get_transfer_history import TransferHistoryItem

from tribulnation.sdk.reporting import (
  Bonus,
  CryptoDeposit,
  CryptoWithdrawal,
  Fee,
  Funding,
  FutureTrade,
  HistoryRecord,
  InternalTransfer,
  Observation,
  Position,
  Snapshot,
  SnapshotRecord,
  SpotTrade,
  SubaccountSnapshot,
  UnknownObservation,
)

env = dotenv_values(repo_root() / '.env')
ADDRESS = env['MARGIN_TRADE_TESTNET_ADDRESS'] or ''
testnet = await MarginTrade.new(public=True, mainnet=False).__aenter__()
mainnet = await MarginTrade.new(public=True).__aenter__()
PERP_TRADER = '9Tdb5DUfoUVnUAGwvfKhsLr8xx3nTzd4VwAw3wDdgaks'
SPOT_TRADER = 'HZEB64qX94oiDsKNisSxYSWuEaKdfsD4Rn1ZEToAw68a'

end = datetime.now(timezone.utc)
start = end - timedelta(days=7)
ADDRESS[:6]

# %% [markdown]
# ## Surface
#
# What the client exposes. Widen or narrow the filter until every endpoint the mapping below uses is listed here.

# %%
from sdk_dev.surface import surface

print(
  surface(
    'typed_margin_trade',
    'MarginTrade',
    grep=r'clearinghouse|fill|funding|transfer|deposit|withdraw|web_data',
  )
)


# %% [markdown]
# ## `snapshot`
#
# Fetch the current balances and positions of the account: a `perp` subaccount (USDC balance and positions) and a `spot` subaccount (token totals, held parts included). The perp `accountValue` includes unrealized PnL, so the balance is `accountValue` minus each position's `unrealizedPnl`; the lifecycle cell checks that figure against the venue's own `perpBalance` (pushed on `webData3` only).

# %%
PERP_ASSET = 'USDC'
"""The perp wallet's only asset: `getTransferHistory` and `webData3.perpBalance` name it `USDC`."""


async def snapshot(
  assets: Collection[str] | None = None, user: str = ADDRESS, via: MarginTrade = testnet
) -> SnapshotRecord:
  state, spot = await asyncio.gather(
    via.info.clearinghouse_state(user=user), via.info.spot_clearinghouse_state(user)
  )
  unrealized = sum(
    (p['position']['unrealizedPnl'] for p in state['assetPositions']), Decimal(0)
  )
  balance = state['marginSummary']['accountValue'] - unrealized
  snap = Snapshot(
    subaccounts=[
      SubaccountSnapshot(
        subaccount='perp',
        balances={PERP_ASSET: balance} if balance else {},
        positions={
          p['position']['coin']: Position(
            size=p['position']['szi'], avg_price=p['position']['entryPx']
          )
          for p in state['assetPositions']
        },
      ),
      SubaccountSnapshot(
        subaccount='spot',
        balances={b['coin']: b['total'] for b in spot['balances'] if b['total']},
      ),
    ]
  )
  return SnapshotRecord(
    snapshot=snap,
    provenance={
      'source': 'api',
      'service': 'margin-trade-testnet',
      'id': snap.time.isoformat(),
    },
  )


(
  await snapshot(),
  await snapshot(user=SPOT_TRADER, via=mainnet),
  await snapshot(user=PERP_TRADER, via=mainnet),
)


# %% [markdown]
# ## `history`
#
# Stream your transaction history as `HistoryRecord`s, each with its `Provenance`:
#
# 1. Fills (`userFillsByTime`, paged backwards): perp fills as `FutureTrade` with `realized_pnl = closedPnl + fee` (the venue's `closedPnl` is net of the fee: an opening fill's equals `-fee`; checked below against a position fold over every fill), spot fills as `SpotTrade`.
# 2. Funding (`userFunding`): `Funding`, signed received-positive.
# 3. Transfers (`getTransferHistory`, the whole history in one response): on-chain deposits and withdrawals, perp/spot transfers (one row per transfer, `venue` naming the credited wallet), faucet credits (testnet `deposit` rows whose `txHash` is `faucet:...`) as `Bonus`; `system` and `liquidation` rows unclassified.


# %%
def fill_record(fill: Fill, perps: set[str], service: str) -> HistoryRecord:
  side = 1 if fill['side'] == 'B' else -1
  fee = Fee(amount=fill['fee'], asset=fill['feeToken'])
  common: dict[str, Any] = {
    'id': f'fill:{fill["tid"]}',
    'time': fill['time'],
    'order_id': str(fill['oid']),
    'fee': fee,
    'price': fill['px'],
    'size': side * fill['sz'],
  }
  if fill['coin'] in perps:
    obs: Observation = FutureTrade(
      **common,
      subaccount='perp',
      instrument=fill['coin'],
      settle=PERP_ASSET,
      realized_pnl=fill['closedPnl'] + fill['fee'],
    )
  else:
    base, quote = fill['coin'].split('/')
    obs = SpotTrade(
      **common, subaccount='spot', pair=fill['coin'], base=base, quote=quote
    )
  return HistoryRecord(
    observations=[obs],
    provenance={
      'source': 'api',
      'service': service,
      'id': f'fill:{fill["tid"]}',
      'details': fill,
    },
  )


def funding_record(row: UserFundingRecord, service: str) -> HistoryRecord:
  delta = row['delta']
  obs = Funding(
    id=f'funding:{row["hash"]}',
    time=row['time'],
    subaccount='perp',
    asset=PERP_ASSET,
    amount=delta['usdc'],
    instrument=delta['coin'],
  )
  return HistoryRecord(
    observations=[obs],
    provenance={
      'source': 'api',
      'service': service,
      'id': f'funding:{row["hash"]}',
      'details': row,
    },
  )


def transfer_observation(row: TransferHistoryItem, id: str) -> Observation:
  common: dict[str, Any] = {
    'id': id,
    'time': row['createdTime'],
    'subaccount': row['venue'],
    'asset': row['asset'],
  }
  tx = row.get('txHash')
  match row['type']:
    case 'deposit' if tx is not None and tx.startswith('faucet:'):
      return Bonus(**common, amount=row['amountChange'], category='faucet')
    case 'deposit':
      return CryptoDeposit(
        **common,
        amount=row['amountChange'],
        network=row.get('chain'),
        tx_id=tx,
        src_address=row['from'] or None,
        dst_address=row['to'] or None,
      )
    case 'withdrawal':
      fee = Fee(amount=row['fee'], asset=row['asset']) if row['fee'] else None
      return CryptoWithdrawal(
        **common,
        amount=row['amountChange'],
        network=row.get('chain'),
        tx_id=tx,
        src_address=row['from'] or None,
        dst_address=row['to'] or None,
        fee=fee,
      )
    case 'transfer':
      other = 'spot' if row['venue'] == 'perp' else 'perp'
      return InternalTransfer(
        **common, amount=row['amount'], src_account=other, dst_account=row['venue']
      )
    case _:
      return UnknownObservation(**common, amount=row['amountChange'])


async def history(
  start: datetime | None = None,
  end: datetime | None = None,
  user: str = ADDRESS,
  via: MarginTrade = testnet,
) -> AsyncIterator[HistoryRecord]:
  service = 'margin-trade-testnet' if via is testnet else 'margin-trade'
  upper = end or datetime.now(timezone.utc)
  lower = start or datetime(2025, 1, 1, tzinfo=timezone.utc)
  perps = {item['name'] for item in (await via.info.meta())['universe']}
  async for page in via.info.user_fills_by_time_paged(
    user, start_time=lower, end_time=upper
  ):
    for fill in page:
      yield fill_record(fill, perps, service)
  for row in await via.info.user_funding(user, start_time=lower, end_time=upper):
    yield funding_record(row, service)
  for row in (await via.user.get_transfer_history(user))['items']:
    if lower <= row['createdTime'] <= upper:
      id = f'transfer:{row["type"]}:{row["venue"]}:{int(row["createdTime"].timestamp() * 1000)}'
      yield HistoryRecord(
        observations=[transfer_observation(row, id)],
        provenance={'source': 'api', 'service': service, 'id': id, 'details': row},
      )


records = [r async for r in history()]
kinds: dict[str, int] = {}
for r in records:
  kinds[r.observations[0].type] = kinds.get(r.observations[0].type, 0) + 1
transfers = [
  r.observations[0]
  for r in records
  if r.observations[0].type not in ('future_trade', 'funding')
]
kinds, transfers, len({r.provenance['id'] for r in records}) == len(records)

# %% [markdown]
# Mainnet accounts: spot fills, funding and on-chain deposits/withdrawals with networks.

# %%
spot_records = [
  r async for r in history(end - timedelta(days=2), end, SPOT_TRADER, mainnet)
]
perp_records = [
  r async for r in history(end - timedelta(days=2), end, PERP_TRADER, mainnet)
]
chains = [
  r.observations[0]
  for r in [r async for r in history(None, None, SPOT_TRADER, mainnet)]
  + [r async for r in history(None, None, PERP_TRADER, mainnet)]
  if r.observations[0].type
  in ('crypto_deposit', 'crypto_withdrawal', 'unknown', 'internal_transfer')
]
{
  'spot kinds': {r.observations[0].type for r in spot_records},
  'spot fill': next(
    r.observations[0] for r in spot_records if r.observations[0].type == 'spot_trade'
  ),
  'perp funding': next(
    r.observations[0] for r in perp_records if r.observations[0].type == 'funding'
  ),
  'transfer rows': chains[:6],
  'networks': {getattr(o, 'network', None) for o in chains},
  'assets': {getattr(o, 'asset', None) for o in chains},
}

# %% [markdown]
# Realized PnL check: fold the testnet account's complete fill history per coin from flat (the venue's `startPosition` is `0` on every fill, closing ones included, so it cannot seed the fold) and compare each fill's price PnL with `closedPnl + fee`.


# %%
def fold_check(fills: list[Fill]) -> tuple[int, int, list[Any]]:
  """`(checked, matching, mismatches)` over perp fills folded from a flat start."""
  state: dict[str, tuple[Decimal, Decimal]] = {}
  matching = 0
  bad: list[Any] = []
  perp = [f for f in sorted(fills, key=lambda f: f['time']) if '/' not in f['coin']]
  for f in perp:
    size = f['sz'] if f['side'] == 'B' else -f['sz']
    pos, entry = state.get(f['coin'], (Decimal(0), Decimal(0)))
    pnl = Decimal(0)
    if pos != 0 and pos * size < 0:
      pnl = min(abs(pos), abs(size)) * (1 if pos > 0 else -1) * (f['px'] - entry)
    after = pos + size
    if pos == 0 or pos * size > 0:
      entry = f['px'] if pos == 0 else (pos * entry + size * f['px']) / after
    elif abs(size) > abs(pos):
      entry = f['px']
    elif after == 0:
      entry = Decimal(0)
    state[f['coin']] = (after, entry)
    if abs(pnl - (f['closedPnl'] + f['fee'])) <= Decimal('0.000002'):
      matching += 1
    else:
      bad.append((f['coin'], f['time'], f['dir'], pnl, f['closedPnl'], f['fee']))
  return len(perp), matching, bad[:5]


mine = await testnet.info.user_fills_by_time(
  ADDRESS, start_time=datetime(2025, 1, 1, tzinfo=timezone.utc)
)
fold_check(mine), {f['startPosition'] for f in mine}, {f['dir'] for f in mine}

# %% [markdown]
# ## Lifecycle
#
# With a 0.001 BTC testnet position open, the snapshot's perp balance (`accountValue - unrealizedPnl`) must equal the venue's own `webData3.perpBalance.total`; the position is then closed.

# %%
agent = await MarginTrade.new(
  env['MARGIN_TRADE_TESTNET_AGENT_PRIVATE_KEY'], vault=ADDRESS, mainnet=False
).__aenter__()
mid = (await agent.info.all_mids())['BTC']
log: dict[str, Any] = {}
await agent.exchange.order(
  [
    {
      'a': 0,
      'b': True,
      'p': Decimal(int(mid * Decimal('1.01'))),
      's': Decimal('0.001'),
      'r': False,
      't': {'limit': {'tif': 'Ioc'}},
    }
  ],
  grouping='na',
)
try:
  await asyncio.sleep(1)
  stream = await agent.streams.web_data3(ADDRESS)
  push = await asyncio.wait_for(anext(aiter(stream)), timeout=20)
  await stream.unsubscribe()
  record = await snapshot()
  log['snapshot perp'] = record.snapshot.subaccounts[0]
  state = push['perpDexStates'][0]['clearinghouseState']
  log['webData3 perpBalance'] = state.get('perpBalance')
  log['webData3 accountValue, uPnL'] = (
    state['marginSummary']['accountValue'],
    [p['position']['unrealizedPnl'] for p in state['assetPositions']],
  )
finally:
  await agent.exchange.order(
    [
      {
        'a': 0,
        'b': False,
        'p': Decimal(int(mid * Decimal('0.99'))),
        's': Decimal('0.001'),
        'r': True,
        't': {'limit': {'tif': 'Ioc'}},
      }
    ],
    grouping='na',
  )
await asyncio.sleep(1)
log['flat'] = (await snapshot()).snapshot.subaccounts[0]
log

# %% [markdown]
# ## Coverage
#
# Status is one of `verified` (executed live, real data), `empty` (executed live, nothing to show on this account), `blocked` (a typed-client issue, numbered in `typed-client-issues.md`), `not supported` (the venue has no such data) or `not attempted`.
#
# | method | status | note |
# |---|---|---|
# | `snapshot` | verified | `perp` USDC without unrealized PnL (matches the fee-adjusted cash; `perpBalance` includes uPnL) and positions; `spot` totals; testnet and two mainnet accounts |
# | `history` | verified | Testnet: 24 fills, funding, 7 perp/spot transfers, a withdrawal, the faucet credit; realized PnL `closedPnl + fee` matches a position fold on all 24 fills; mainnet: spot fills, funding, PRL withdrawals on `pearl` |

# %% [markdown]
# ## Catalogue
#
# Every ID the verified methods returned, minus what the catalogue translates for this platform. Anything listed is a catalogue addition to make, not something to rename here: the SDK emits venue-native IDs and the catalogue maps them.

# %%
from sdk_dev.catalogue import Ids, gap, load_catalogue

found = Ids()
for rec in [
  await snapshot(),
  await snapshot(user=SPOT_TRADER, via=mainnet),
  await snapshot(user=PERP_TRADER, via=mainnet),
]:
  for sub in rec.snapshot.subaccounts:
    found.assets |= set(sub.balances)
    found.positions |= {f'perp:{p}' for p in sub.positions}
for obs in [r.observations[0] for r in records + spot_records + perp_records] + chains:
  if (asset := getattr(obs, 'asset', None)) is not None:
    found.assets.add(asset)
  if (network := getattr(obs, 'network', None)) is not None:
    found.networks.add(network)
  if (fee := getattr(obs, 'fee', None)) is not None:
    found.assets.add(fee.asset)
gap('margin-trade', found, load_catalogue(root=repo_root()))

# %%
await testnet.__aexit__(None, None, None)  # pyright: ignore[reportUnknownMemberType] -- upstream lifecycle parameters are untyped
await mainnet.__aexit__(None, None, None)  # pyright: ignore[reportUnknownMemberType] -- upstream lifecycle parameters are untyped
await agent.__aexit__(None, None, None)  # pyright: ignore[reportUnknownMemberType] -- upstream lifecycle parameters are untyped
