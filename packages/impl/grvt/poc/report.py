# %% [markdown]
# # grvt `report` PoC
#
# Maps `typed_grvt` onto the SDK `report` surface, one method per cell, each executed live. The rules, and how a typed-client issue is reported in `typed-client-issues.md`, are in `.agents/skills/sdk-poc/SKILL.md`.
#
# Read-only, with an API key and no signer. A GRVT funding (main) account, identified
# by an EVM address, owns a `FUNDING` wallet and its vault investments, and links to
# trading sub-accounts (numeric ids), each with a `FUTURES` and a `SPOT` wallet (the
# venue's `WalletType`). Every cell runs twice: on **mainnet** (`GRVT_API_KEY`,
# `GRVT_TRADING_ACCOUNT_ID`; an unfunded account, so mostly empty) and on **testnet**
# (`GRVT_TESTNET_*`; about 20k USDT across the funding and trading accounts), so every
# mapping meets non-zero data. Asset IDs are the venue's currency codes (`USDT`), and
# position IDs its instrument names (`BTC_USDT_Perp`). Account ids and addresses are
# never displayed: sub-account labels are masked by position.

# %%
from datetime import datetime
from decimal import Decimal
from typing_extensions import AsyncIterable, Collection
import asyncio

from dotenv import load_dotenv
from typed_grvt import Grvt
from typed_grvt.core.exc import ApiError, BadRequest
from typed_grvt.schemas import SpotBalance
from typed_grvt.trading.account_summary import SubAccount
from sdk_dev.repo import repo_root
from tribulnation.sdk.reporting import (
  HistoryRecord,
  Position,
  Snapshot,
  SnapshotRecord,
  SubaccountSnapshot,
)

load_dotenv(repo_root() / '.env')

mainnet = await Grvt.new().__aenter__()
testnet = await Grvt.new(env='testnet').__aenter__()
client = mainnet
NETWORKS = {'grvt': mainnet, 'grvt_testnet': testnet}

# %% [markdown]
# ## Surface
#
# What the client exposes. Widen or narrow the filter until every endpoint the mapping below uses is listed here.

# %%
from sdk_dev.surface import surface

print(
  surface(
    'typed_grvt',
    'Grvt',
    grep=r'account_summary|sub_accounts|positions$|vault_investor_summary|investment_strategies',
  )
)


# %% [markdown]
# ## `snapshot`
#
# Fetch the current balances and positions of the account.
#
# One subaccount per wallet, named after the venue's `WalletType`:
#
# 1. `funding`: the funding account's `spot_balances` (`funding_account_summary`).
# 2. `<sub_account_id>:futures`: each trading sub-account's `spot_balances` and open
#    `positions` (`account_summary`), for every id `sub_accounts` lists. The balances
#    are cash, without unrealized PnL: the venue documents `total_equity` as
#    `sum(balance * index_price) / settle_index_price + unrealized_pnl`, checked below.
#    Positions are keyed by instrument name, `size` signed (negative short), at
#    `entry_price`.
# 3. `<sub_account_id>:spot`: the same sub-account's spot wallet
#    (`spot_account_summary`).
#
# Three branches no account here can produce, so they raise instead of guessing: a
# vault investment (the funding account's `vault_investments`, valued only in USD per LP
# token), a non-zero `borrowed_amount` (a multi-asset-mode borrow, whose relation to
# `balance` is undocumented), and a sub-account that is itself a vault (`is_vault`,
# whose holdings belong to every investor).

# %%
FUNDING = 'funding'
"""The funding account's wallet; one main account per API key."""


def held(balances: list[SpotBalance]) -> dict[str, Decimal]:
  """Non-zero balances by currency code.

  Raises:
    NotImplementedError: A borrowed currency: whether `balance` nets the borrow is
      unverified.
  """
  for b in balances:
    if b.get('borrowed_amount'):
      raise NotImplementedError(
        f'GRVT borrowed {b["currency"]}: whether `balance` nets it is unverified'
      )
  return {b['currency']: b['balance'] for b in balances if b['balance']}


def positions(summary: SubAccount) -> dict[str, Position]:
  """Open positions by instrument name, signed, at their entry price."""
  return {
    p['instrument']: Position(size=p['size'], avg_price=p['entry_price'])
    for p in summary['positions']
    if p['size']
  }


async def wallets(grvt: Grvt, id: str) -> list[SubaccountSnapshot]:
  """One trading sub-account's futures wallet, with its positions, and spot wallet."""
  futures, spot = await asyncio.gather(
    grvt.trading.account_summary(id), grvt.trading.spot_account_summary(id)
  )
  if futures.get('is_vault'):
    raise NotImplementedError('GRVT vault sub-accounts are not mapped')
  return [
    SubaccountSnapshot(
      subaccount=f'{id}:futures',
      balances=held(futures['spot_balances']),
      positions=positions(futures),
    ),
    SubaccountSnapshot(subaccount=f'{id}:spot', balances=held(spot['spot_balances'])),
  ]


async def snapshot_of(grvt: Grvt, *, service: str) -> SnapshotRecord:
  """The funding wallet, and both wallets of every accessible sub-account."""
  funding, subs = await asyncio.gather(
    grvt.trading.funding_account_summary(), grvt.trading.sub_accounts()
  )
  if funding['result']['vault_investments']:
    raise NotImplementedError('GRVT vault investments are not mapped')
  states = [
    SubaccountSnapshot(
      subaccount=FUNDING, balances=held(funding['result']['spot_balances'])
    )
  ]
  for parts in await asyncio.gather(
    *(wallets(grvt, id) for id in subs['sub_account_ids'])
  ):
    states.extend(parts)
  snap = Snapshot(subaccounts=states)
  return SnapshotRecord(
    snapshot=snap,
    provenance={'source': 'api', 'service': service, 'id': snap.time.isoformat()},
  )


async def snapshot(assets: Collection[str] | None = None) -> SnapshotRecord:
  """Mainnet snapshot; `assets` is ignored, the venue enumerates holdings."""
  return await snapshot_of(client, service='grvt')


def shown(record: SnapshotRecord) -> list[tuple[str, dict[str, Decimal], list[str]]]:
  """Each subaccount's label, with the sub-account id masked, balances and positions."""
  masks: dict[str, str] = {}
  rows: list[tuple[str, dict[str, Decimal], list[str]]] = []
  for state in record.snapshot.subaccounts:
    label = state.subaccount or ''
    head, sep, wallet = label.partition(':')
    if sep:
      label = f'<sub {masks.setdefault(head, str(len(masks)))}>:{wallet}'
    rows.append(
      (
        label,
        state.balances,
        [f'{k} {p.size} @ {p.avg_price}' for k, p in state.positions.items()],
      )
    )
  return rows


shown(await snapshot())

# %% [markdown]
# The same mapping on testnet, where the funding and trading wallets are funded.

# %%
shown(await snapshot_of(testnet, service='grvt_testnet'))

# %% [markdown]
# Reconcile with the venue's own totals: `aggregated_account_summary.spot_balances` sums
# the funding account and every sub-account per currency, so it equals the snapshot's
# aggregated balances when no wallet is missing or counted twice.


# %%
async def reconcile(grvt: Grvt, service: str) -> list[tuple[str, Decimal, Decimal]]:
  """Each currency's snapshot total beside the venue's aggregated total."""
  record, aggregated = await asyncio.gather(
    snapshot_of(grvt, service=service), grvt.trading.aggregated_account_summary()
  )
  ours = record.snapshot.balances
  venue = {b['currency']: b['balance'] for b in aggregated['spot_balances']}
  return [
    (c, ours.get(c, Decimal(0)), venue.get(c, Decimal(0)))
    for c in sorted(set(ours) | set(venue))
  ]


{service: await reconcile(grvt, service) for service, grvt in NETWORKS.items()}

# %% [markdown]
# Balances exclude unrealized PnL: each sub-account's `total_equity` matches the venue's
# documented formula over the `balance`s the snapshot reports. Last run while the
# testnet sub-account held the funding position (234 BARD long, cross), so the formula
# carried a non-zero `unrealized_pnl`; an isolated position remains unchecked.


# %%
async def equity(grvt: Grvt) -> list[tuple[int, Decimal, Decimal | None]]:
  """Each sub-account's `total_equity` beside the documented formula, by position."""
  rows: list[tuple[int, Decimal, Decimal | None]] = []
  for i, id in enumerate((await grvt.trading.sub_accounts())['sub_account_ids']):
    s = await grvt.trading.account_summary(id)
    value = sum(
      (b['balance'] * b['index_price'] for b in s['spot_balances']), Decimal(0)
    )
    formula = (
      value / s['settle_index_price'] + s['unrealized_pnl']
      if s['settle_index_price']
      else None
    )
    rows.append((i, s['total_equity'], formula))
  return rows


{service: await equity(grvt) for service, grvt in NETWORKS.items()}

# %% [markdown]
# Vaults: neither funding account holds a vault investment, and `vault_investor_summary`
# answers `7007` for a vault the account is not an LP of. The vault listing is on the
# edge host, which Cloudflare blocks for scripted clients on mainnet (`403`); testnet
# serves it. A vault's own sub-account is not readable by an investor (`1001`), so a
# claim could only be valued from `num_lp_tokens` and the USD `share_price`.

# %%
invested = {
  service: len(
    (await grvt.trading.funding_account_summary())['result']['vault_investments']
  )
  for service, grvt in NETWORKS.items()
}
vault = (await testnet.edge.investment_strategies())['strategies'][0]['chain_vault_id']
try:
  await testnet.trading.vault_investor_summary(vault)
  lp = 'an LP'
except BadRequest as e:
  lp = e.args[:2]
try:
  await testnet.trading.account_summary(vault)
  readable = 'readable'
except ApiError as e:
  readable = e.args[:2]
try:
  await mainnet.edge.investment_strategies()
  listing = 'served'
except ApiError as e:
  listing = (type(e).__name__, e.args[0])
(invested, lp, readable, listing)


# %% [markdown]
# ## `history`
#
# Stream your transaction history as `HistoryRecord`s, each with its `Provenance`.


# %%
async def history(
  start: datetime | None = None, end: datetime | None = None
) -> AsyncIterable[HistoryRecord]:
  """Not mapped: `history()` is being retired from the Report surface."""
  raise NotImplementedError('GRVT report history is not supported')
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
# | `snapshot` | verified | Testnet: USDT, USDC and GRVT across the `funding` and `<sub>:futures` wallets, reconciling per currency with `aggregated_account_summary` and per sub-account with `total_equity`; re-run while holding the funding position (234 BARD long), the position maps by instrument name at its entry price and `total_equity` still matches the formula over the cash balances plus `unrealized_pnl`. Mainnet: runs (10 USDT funded since). No account holds a spot-wallet balance, a borrow or a vault investment; borrows, vault investments and vault sub-accounts raise `NotImplementedError` until a live sample settles them |
# | `history` | not attempted | The Report history surface is being retired |

# %% [markdown]
# ## Catalogue
#
# Every ID the verified methods returned, minus what the catalogue translates for this platform. Anything listed is a catalogue addition to make, not something to rename here: the SDK emits venue-native IDs and the catalogue maps them.

# %%
from sdk_dev.catalogue import Ids, gap, load_catalogue

ids = Ids()
for service, grvt in NETWORKS.items():
  record = await snapshot_of(grvt, service=service)
  ids.merge(
    Ids(assets=set(record.snapshot.balances), positions=set(record.snapshot.positions))
  )
gap('grvt', ids, load_catalogue(root=repo_root()))

# %%
for grvt in NETWORKS.values():
  await grvt.__aexit__(None, None, None)  # pyright: ignore[reportUnknownMemberType] -- upstream lifecycle parameters are untyped
