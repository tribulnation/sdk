# %% [markdown]
# # extended `report` PoC
#
# Maps `typed_extended` onto the SDK `report` surface, one method per cell, each executed live. The rules, and how a typed-client issue is reported in `typed-client-issues.md`, are in `.agents/skills/sdk-poc/SKILL.md`.
#
# Every read uses an API key alone (read-only: `dotenv_values` keeps the Stark keys out of
# the environment the client falls back to), and no cell changes state. Two accounts, from
# the repo-root `.env`:
#
# 1. Mainnet (`EXTENDED_API_KEY`): the primary account, a main sub-account with no funds,
#    which proves the empty paths (the venue answers `404` instead of an empty balance,
#    which the client reads as `None` and `[]`).
# 2. Testnet (`EXTENDED_TESTNET_API_KEY`): a throwaway Sepolia main sub-account with about
#    1000 test USD, closed ETH-USD round trips, transfers to and from sub-account 1 and one
#    bridge withdrawal, which proves the non-empty shapes.
#
# An API key belongs to one sub-account of a wallet. Asset IDs are the venue's asset names
# (`USD`, `BTCSPOT`, `XVS`), position and fill instruments its market names (`ETH-USD`),
# and each snapshot subaccount and observation is labelled with the sub-account's
# `accountId`.

# %%
import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing_extensions import Any, AsyncIterator, Awaitable, Collection

from dotenv import dotenv_values
from sdk_dev.repo import repo_root
from typed_extended import AuthError, Extended
from typed_extended.account.asset_operations import AssetOperation
from typed_extended.account.positions_history import PositionHistory
from typed_extended.account.trades import AccountTrade
from typed_extended.info.markets import Market

from tribulnation.sdk.reporting import (
  Bonus,
  CryptoDeposit,
  CryptoWithdrawal,
  Fee,
  FeeLeg,
  FuturePositionSummary,
  FutureTrade,
  HistoryRecord,
  InternalTransfer,
  Observation,
  Position,
  Snapshot,
  SnapshotRecord,
  SpotTrade,
  SubaccountSnapshot,
)

env = dotenv_values(repo_root() / '.env')
mainnet = await Extended.new(api_key=env['EXTENDED_API_KEY']).__aenter__()
testnet = await Extended.new(
  network='testnet', api_key=env['EXTENDED_TESTNET_API_KEY']
).__aenter__()
EPOCH = datetime(2020, 1, 1, tzinfo=timezone.utc)
"""Default lower bound: `funding_history` requires a start time."""


def service(client: Extended) -> str:
  """Provenance service of a client's network."""
  return 'extended' if client.network.name == 'mainnet' else 'extended-testnet'


[
  (c.network.name, c.credentials is not None and c.credentials.stark is None)
  for c in (mainnet, testnet)
]

# %% [markdown]
# ## Surface
#
# What the client exposes. Widen or narrow the filter until every endpoint the mapping below uses is listed here.

# %%
from sdk_dev.surface import surface

print(
  surface(
    'typed_extended',
    'Extended',
    grep=r'^(account\.(info|sub_accounts|spot_balances|balance|positions|positions_history_paged|trades_paged|funding_history_paged|asset_operations_paged)|info\.(assets|markets)|interest\.(payments|key_metrics)|portfolio\.(summary|health)|vault\.)\b',
  )
)


# %% [markdown]
# ## `snapshot`
#
# Fetch the current balances and positions of the account.
#
# One subaccount, the API key's own sub-account (`<accountId>`): `spot_balances` lists
# every asset it holds, the collateral (`USD`) included, and `positions` its open
# perpetual positions by market. The venue answers `404` instead of an empty list when the
# sub-account holds nothing at all (the mainnet account), which the client returns as `[]`.


# %%
async def snapshot(
  assets: Collection[str] | None = None, client: Extended = mainnet
) -> SnapshotRecord:
  """The API key's sub-account: its holdings and open perpetual positions."""
  info, rows, positions = await asyncio.gather(
    client.account.info(), client.account.spot_balances(), client.account.positions()
  )
  sub = SubaccountSnapshot(
    subaccount=str(info['accountId']),
    balances={r['asset']: r['balance'] for r in rows if r['balance']},
    positions={
      p['market']: Position(
        size=p['size'] if p['side'] == 'LONG' else -p['size'], avg_price=p['openPrice']
      )
      for p in positions
    },
  )
  snap = Snapshot(subaccounts=[sub])
  return SnapshotRecord(
    snapshot=snap,
    provenance={
      'source': 'api',
      'service': service(client),
      'id': snap.time.isoformat(),
    },
  )


(
  (await snapshot()).snapshot.subaccounts,
  (await snapshot(client=testnet)).snapshot.subaccounts,
)

# %% [markdown]
# Reconcile with the venue's own balance: the collateral row of `spot_balances` is the
# wallet balance (`deposits - withdrawals + realised PnL`, without unrealised PnL), and the
# other rows' `equityContribution` sum to `spotEquity`. Checked on testnet while flat (no
# position may be opened here). The mainnet account's `balance` is `None` (the venue's
# `404`) as well.

# %%
bal = await testnet.account.balance()
assert bal is not None
rows = await testnet.account.spot_balances()
collateral = bal['collateralName']
{
  'collateral row == balance': next(
    r['balance'] for r in rows if r['asset'] == collateral
  )
  == bal['balance'],
  'unrealisedPnl': bal['unrealisedPnl'],
  'other rows == spotEquity': sum(
    (r['equityContribution'] for r in rows if r['asset'] != collateral), Decimal(0)
  )
  == bal.get('spotEquity', Decimal(0)),
  'mainnet balance()': await mainnet.account.balance(),
}

# %% [markdown]
# ### What one API key reads
#
# `sub_accounts` lists every sub-account of the wallet, but every balance, position and
# history read is scoped to the key's own sub-account; the client offers no filter for
# another sub-account's balances. The account-scoped `portfolio` and `interest` reads
# answer `403` for sub-account 1.


# %%
async def outcome(call: Awaitable[Any]) -> Any:
  """The call's result, or the auth error it raised."""
  try:
    return await call
  except AuthError as exc:
    return f'AuthError{exc.args[:1]}'


own = (await testnet.account.info())['accountId']
subs = await testnet.account.sub_accounts()
other = next(s['accountId'] for s in subs if s['accountId'] != own)
{
  'sub_accounts': [(s['accountId'], s['accountIndex'], s['status']) for s in subs],
  'spot_balances()': [
    (r['accountId'], r['asset']) for r in await testnet.account.spot_balances()
  ],
  'portfolio.health([other])': await outcome(testnet.portfolio.health([other])),
  'portfolio.summary([own, other])': await outcome(
    testnet.portfolio.summary([own, other], interval='DAY')
  ),
  'interest.key_metrics([other])': await outcome(testnet.interest.key_metrics([other])),
}

# %% [markdown]
# ### Vault shares
#
# The client's `vault` namespace covers the public vault only (summary, performance).
# Shares are the spot asset `XVS` (`isVaultShare`), so a holder's shares would be a
# `spot_balances` row the snapshot already maps; `portfolio.summary` reports the
# sub-account's vault holding only as a USD notional (`vaultNotionalValue`), which is not
# a share balance. Neither account holds any.

# %%
vault_value: dict[str, Any] = {}
for c in (mainnet, testnet):
  account_id = (await c.account.info())['accountId']
  summary = await c.portfolio.summary([account_id], interval='DAY')
  vault_value[c.network.name] = summary['accountValue']
(
  [
    (a['name'], a['id'])
    for a in await mainnet.info.assets(type='SPOT')
    if a.get('isVaultShare')
  ],
  vault_value,
)


# %% [markdown]
# ## `history`
#
# Stream your transaction history as `HistoryRecord`s, each with its `Provenance`:
#
# 1. Asset operations (`asset_operations`, bounded server-side): completed transfers
#    between the wallet's sub-accounts as `InternalTransfer` (the venue reports them from
#    the key's side: `accountId` is the key's sub-account and the amount's sign gives the
#    direction), completed deposits as `CryptoDeposit`, testnet `CLAIM`s as `Bonus`, and
#    withdrawals that are not `REJECTED` as `CryptoWithdrawal` (the balance is debited on
#    creation: the testnet withdrawal is `IN_PROGRESS` and already out of `balance`).
#    The numeric asset id is translated to its name through `info.assets`.
# 2. Fills (`trades`, newest first, at most 10,000): `FutureTrade` on perpetual markets,
#    `SpotTrade` on spot markets (`info.markets` `type`), with the fee in the collateral
#    asset (an order's signed `fee_asset_id` is the collateral). Fills carry no realised PnL.
# 3. Closed positions (`positions_history`): `FuturePositionSummary`, the venue's realised
#    PnL breakdown. `realisedPnl = tradePnl + openFees + closeFees + fundingFees`, fees
#    negative, so `realized_pnl` is `tradePnl` and the fees are negated.
# 4. Funding payments and borrow interest are not mapped: neither account has one, and
#    neither the sign of `fundingFee` nor of `paymentAmount` is documented. History raises
#    `NotImplementedError` when either is present rather than drop or guess them.


# %%
def operation(row: AssetOperation, names: dict[int, str]) -> list[Observation]:
  """One asset operation as observations; none when it moved no funds."""
  me = str(row['accountId'])
  asset = names[row['asset']]
  common: dict[str, Any] = {
    'id': f'operation:{row["id"]}',
    'time': row['time'],
    'subaccount': me,
    'asset': asset,
  }
  fee = Fee(amount=row['fee'], asset=asset) if row['fee'] else None
  status = row['status']
  match row['type']:
    case 'TRANSFER' if status == 'COMPLETED':
      peer = row.get('counterpartyAccountId')
      out = row['amount'] < 0
      there = str(peer) if peer is not None else None
      moved: list[Observation] = [
        InternalTransfer(
          **common,
          amount=abs(row['amount']),
          src_account=me if out else there,
          dst_account=there if out else me,
        )
      ]
      if fee is not None:
        moved.append(
          FeeLeg(**common, amount=fee.amount, event_type='internal_transfer')
        )
      return moved
    case 'DEPOSIT' if status == 'COMPLETED':
      return [
        CryptoDeposit(
          **common,
          amount=row['amount'],
          network=row.get('chain'),
          tx_id=row.get('transactionHash'),
          fee=fee,
        )
      ]
    case 'CLAIM' if status == 'COMPLETED':
      return [Bonus(**common, amount=row['amount'], category='claim')]
    case 'WITHDRAWAL' | 'FAST_WITHDRAWAL' | 'SLOW_WITHDRAWAL' if status != 'REJECTED':
      return [
        CryptoWithdrawal(
          **common,
          amount=row['amount'],
          network=row.get('chain'),
          tx_id=row.get('transactionHash'),
          fee=fee,
        )
      ]
    case _:
      return []


def fill(row: AccountTrade, markets: dict[str, Market]) -> Observation:
  """One fill: a perpetual `FutureTrade` or a `SpotTrade`."""
  if row.get('builderFee'):
    raise NotImplementedError(
      'builder fee: whether `fee` includes `builderFee` is unobserved'
    )
  market = markets[row['market']]
  quote = market['collateralAssetName']
  common: dict[str, Any] = {
    'id': f'trade:{row["id"]}',
    'time': row['createdTime'],
    'subaccount': str(row['accountId']),
    'base': market['assetName'],
    'quote': quote,
    'size': row['qty'] if row['side'] == 'BUY' else -row['qty'],
    'price': row['price'],
    'order_id': str(row['orderId']),
    'fee': Fee(amount=row['fee'], asset=quote),
  }
  if market['type'] == 'SPOT':
    return SpotTrade(**common, pair=row['market'])
  return FutureTrade(**common, instrument=row['market'], settle=quote)


def position(row: PositionHistory, markets: dict[str, Market]) -> Observation:
  """One closed position's realised PnL breakdown."""
  market = markets[row['market']]
  quote = market['collateralAssetName']
  parts = row.get('realisedPnlBreakdown')
  return FuturePositionSummary(
    id=f'position:{row["id"]}',
    time=row.get('closedTime'),
    subaccount=str(row['accountId']),
    position_id=str(row['id']),
    instrument=row['market'],
    base=market['assetName'],
    quote=quote,
    settle=quote,
    position_side='long' if row['side'] == 'LONG' else 'short',
    opened_at=row['createdTime'],
    closed_at=row.get('closedTime'),
    avg_entry_price=row['openPrice'],
    avg_close_price=row.get('exitPrice'),
    realized_pnl=parts['tradePnl'] if parts else None,
    funding=parts['fundingFees'] if parts else None,
    opening_fee=-parts['openFees'] if parts else None,
    closing_fee=-parts['closeFees'] if parts else None,
    total_fee=-(parts['openFees'] + parts['closeFees']) if parts else None,
    position_pnl=row['realisedPnl'],
  )


def record(observations: list[Observation], row: Any, service: str) -> HistoryRecord:
  """Observations with their provenance: the venue row."""
  return HistoryRecord(
    observations=observations,
    provenance={
      'source': 'api',
      'service': service,
      'id': observations[0].id or '',
      'details': row,
    },
  )


async def history(
  start: datetime | None = None,
  end: datetime | None = None,
  client: Extended = mainnet,
) -> AsyncIterator[HistoryRecord]:
  """The API key's sub-account: asset operations, fills and closed positions."""
  lower = start or EPOCH
  upper = end or datetime.now(timezone.utc)
  me = (await client.account.info())['accountId']
  names = {a['id']: a['name'] for a in await client.info.assets(type='SPOT')}
  markets = {m['name']: m for m in await client.info.markets()}
  funding = await client.account.funding_history_paged(start_time=lower)
  interest = (await client.interest.payments([me], interval='ALL'))['items']
  if any(p['paidTime'] <= upper for p in funding) or any(
    lower <= p['timestamp'] <= upper for p in interest
  ):
    raise NotImplementedError(
      'funding and interest payments: their sign is undocumented and unobserved'
    )
  svc = service(client)
  for row in await client.account.asset_operations_paged(
    start_time=lower, end_time=upper
  ):
    if observations := operation(row, names):
      yield record(observations, row, svc)
  async for page in client.account.trades_paged():
    for row in page:
      if lower <= row['createdTime'] <= upper:
        yield record([fill(row, markets)], row, svc)
    if page[-1]['createdTime'] < lower:
      break
  for row in await client.account.positions_history_paged():
    closed = row.get('closedTime')
    if closed is not None and lower <= closed <= upper:
      yield record([position(row, markets)], row, svc)


records = [r async for r in history(client=testnet)]
kinds: dict[str, int] = {}
for r in records:
  kinds[r.observations[0].type] = kinds.get(r.observations[0].type, 0) + 1
(
  kinds,
  len({r.provenance['id'] for r in records}) == len(records),
  [r.observations[0] for r in records if r.observations[0].type != 'future_trade'],
  next(r.observations[0] for r in records if r.observations[0].type == 'future_trade'),
  [r async for r in history()],
)

# %% [markdown]
# Reconcile with the testnet balance: the asset operations plus each closed position's
# realised PnL (fees included) give the collateral balance, and the fills' fees equal the
# positions' opening and closing fees.

# %%
flow = Decimal(0)
fill_fees = Decimal(0)
summary_fees = Decimal(0)
for r in records:
  obs = r.observations[0]
  match obs:
    case InternalTransfer():
      flow += obs.amount if obs.dst_account == str(own) else -obs.amount
    case Bonus() | CryptoDeposit() | CryptoWithdrawal():
      flow += obs.balance_change
    case FuturePositionSummary():
      flow += obs.position_pnl or 0
      summary_fees += obs.total_fee or 0
    case FutureTrade() | SpotTrade():
      fill_fees += obs.fee.amount if obs.fee else 0
    case _:
      pass
(flow, bal['balance'], fill_fees == summary_fees)

# %% [markdown]
# ## Coverage
#
# Status is one of `verified` (executed live, real data), `empty` (executed live, nothing to show on this account), `blocked` (a typed-client issue, numbered in `typed-client-issues.md`), `not supported` (the venue has no such data) or `not attempted`.
#
# | method | status | note |
# |---|---|---|
# | `snapshot` | verified | The API key's own sub-account (`<accountId>`): `spot_balances`, collateral included, and `positions` by market. Testnet: 994.79 USD, matching `balance` and `spotEquity`; mainnet: the empty account, whose `404` the client reads as no rows. Another sub-account needs its own key. No open position or non-USD holding on either account (opening one changes state); `XVS` vault shares would be a spot row, not observed |
# | `history` | verified | Testnet: the faucet claim, transfers to and from sub-account 1, an in-progress BASE withdrawal, 4 ETH-USD fills and 2 closed positions; operations plus positions' realised PnL reconcile with the balance, fill fees with the positions' fees. Mainnet: nothing to show. Not exercised: deposits, spot fills. Funding payments and borrow interest raise `NotImplementedError`: their sign is undocumented and neither account has one |

# %% [markdown]
# ## Catalogue
#
# Every ID the verified methods returned, minus what the catalogue translates for this platform. Anything listed is a catalogue addition to make, not something to rename here: the SDK emits venue-native IDs and the catalogue maps them.

# %%
from sdk_dev.catalogue import Ids, gap, load_catalogue

found = Ids()
for rec in (await snapshot(), await snapshot(client=testnet)):
  found.assets |= set(rec.snapshot.balances)
  found.positions |= set(rec.snapshot.positions)
for r in records:
  for obs in r.observations:
    if (asset := getattr(obs, 'asset', None)) is not None:
      found.assets.add(asset)
    if (network := getattr(obs, 'network', None)) is not None:
      found.networks.add(network)
    if (fee := getattr(obs, 'fee', None)) is not None:
      found.assets.add(fee.asset)
    if isinstance(obs, FutureTrade | FuturePositionSummary) and obs.instrument:
      found.perp_markets.add(obs.instrument)
gap('extended', found, load_catalogue(root=repo_root()))

# %%
await mainnet.__aexit__(None, None, None)  # pyright: ignore[reportUnknownMemberType] -- upstream lifecycle parameters are untyped
await testnet.__aexit__(None, None, None)  # pyright: ignore[reportUnknownMemberType] -- upstream lifecycle parameters are untyped
