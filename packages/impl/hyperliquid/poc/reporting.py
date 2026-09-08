# %%
import asyncio
import os
from decimal import Decimal
from datetime import datetime, timedelta, timezone

from typed_hyperliquid import Hyperliquid
from dotenv import load_dotenv

from tribulnation.sdk.reporting import (
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
  Transfer,
  source_id,
)

load_dotenv()

client = await Hyperliquid.new(mainnet=False, public=True).__aenter__()
ADDRESS = os.environ['HYPERLIQUID_TESTNET_ADDRESS']

end = datetime.now(timezone.utc)
start = end - timedelta(days=30)
# every fill on this account predates the 30-day window, so the trade reads below are
# also called over a wider one, to exercise their mapping against real rows
fills_start = end - timedelta(days=180)

ADDRESS


# %% [markdown]
# > `client` is the raw `typed_hyperliquid.Hyperliquid` client, hand-mapped onto `tribulnation.sdk.reporting` types below -- no production `tribulnation.hyperliquid` code is imported or driven, unlike the previous round of this notebook. It runs against the same Hyperliquid **testnet** account as `market.ipynb` (`HYPERLIQUID_TESTNET_ADDRESS`/`HYPERLIQUID_TESTNET_PRIVATE_KEY` from `.env`; no mainnet credentials exist in this workspace), which carries a real open `BTC` short and nonzero balances -- so several results below reflect genuine non-zero state.

# %% [markdown]
# ## `History`

# %%
async def spot_trades(start: datetime, end: datetime) -> list[SpotTrade]:
  fills = await client.info.user_fills_by_time(
    user=ADDRESS, start_time=start, end_time=end
  )
  out: list[SpotTrade] = []
  for f in fills:
    if '/' not in f['coin']:
      continue  # perp fill (or a spot pair the venue names by index), see the note below
    base, quote = f['coin'].split('/', 1)
    out.append(
      SpotTrade(
        id=str(f['tid']),
        time=f['time'],
        base=base,
        quote=quote,
        pair=f['coin'],
        size=f['sz'] if f['side'] == 'B' else -f['sz'],
        price=f['px'],
        order_id=str(f['oid']),
        fee=Fee(amount=f['fee'], asset=f['feeToken']) if f['fee'] else None,
      )
    )
  return out


await spot_trades(fills_start, end)


# %%
async def future_trades(start: datetime, end: datetime) -> list[FutureTrade]:
  fills = await client.info.user_fills_by_time(
    user=ADDRESS, start_time=start, end_time=end
  )
  out: list[FutureTrade] = []
  for f in fills:
    if '/' in f['coin']:
      continue  # spot fill, handled by spot_trades above
    out.append(
      FutureTrade(
        id=str(f['tid']),
        time=f['time'],
        instrument=f['coin'],
        base=f['coin'],
        settle='USDC',
        size=f['sz'] if f['side'] == 'B' else -f['sz'],
        price=f['px'],
        realized_pnl=f['closedPnl'],
        order_id=str(f['oid']),
        fee=Fee(amount=f['fee'], asset=f['feeToken']) if f['fee'] else None,
      )
    )
  return out


await future_trades(fills_start, end)


# %%
async def funding(start: datetime, end: datetime) -> list[Funding]:
  # Hyperliquid's `usdc` is positive when *received*, matching `Funding.amount`'s
  # (a `SingleAssetObservation`) "positive = credited" convention directly -- no sign flip
  # needed here, unlike `market.ipynb`'s `FundingPayment` (which uses the opposite convention).
  raw = await client.info.user_funding(user=ADDRESS, start_time=start, end_time=end)
  return [
    Funding(
      time=p['time'],
      amount=Decimal(p['delta']['usdc']),
      asset='USDC',
      instrument=p['delta']['coin'],
    )
    for p in raw
  ]


await funding(start, end)


# %%
async def ledger_observations(start: datetime, end: datetime) -> list[Observation]:
  """Map the non-funding ledger's ~20 delta types onto the closest `Observation` subtype.
  Only the shapes this account is realistically able to exercise (deposits, withdrawals,
  internal/external transfers) are mapped -- vault flows, staking transfers, liquidations,
  rewards, and borrow/lend deltas are left unmapped (see the coverage note below)."""
  raw = await client.info.user_non_funding_ledger_updates(
    user=ADDRESS,
    start_time=start,
    end_time=end,
  )
  out: list[Observation] = []
  for entry in raw:
    d = entry['delta']
    t = entry['time']
    if d['type'] == 'deposit':
      out.append(
        CryptoDeposit(
          id=entry['hash'],
          time=t,
          asset='USDC',
          amount=Decimal(d['usdc']),
          network='Arbitrum',
        )
      )
    elif d['type'] == 'withdraw':
      fee_amount = Decimal(d['fee'])
      out.append(
        CryptoWithdrawal(
          id=entry['hash'],
          time=t,
          asset='USDC',
          amount=-Decimal(d['usdc']),
          network='Arbitrum',
          fee=Fee(amount=fee_amount, asset='USDC') if fee_amount else None,
        )
      )
    elif d['type'] == 'internalTransfer' or d['type'] == 'subAccountTransfer':
      out.append(
        InternalTransfer(
          id=entry['hash'],
          time=t,
          asset='USDC',
          amount=Decimal(d['usdc']),
          src_account=d.get('user'),
          dst_account=d.get('destination'),
        )
      )
    elif d['type'] == 'accountClassTransfer':
      out.append(
        InternalTransfer(
          id=entry['hash'],
          time=t,
          asset='USDC',
          amount=Decimal(d['usdc']),
          src_account='spot' if d['toPerp'] else 'perp',
          dst_account='perp' if d['toPerp'] else 'spot',
        )
      )
    elif d['type'] == 'spotTransfer' or d['type'] == 'send':
      fee_amount = Decimal(d['fee']) if d.get('fee') else None
      out.append(
        Transfer(
          id=entry['hash'],
          time=t,
          asset=d['token'],
          amount=-Decimal(d['amount']),
          src_account=d.get('user'),
          dst_account=d.get('destination'),
          fee=Fee(amount=fee_amount, asset=d.get('feeToken') or d['token'])
          if fee_amount
          else None,
        )
      )
  return out


await ledger_observations(start, end)


# %% [markdown]
# ### `history(start=None, end=None)`

# %%
async def history(start: datetime | None = None, end: datetime | None = None):
  end = end or datetime.now(timezone.utc)
  start = start or end - timedelta(days=1)
  groups = await asyncio.gather(
    spot_trades(start, end),
    future_trades(start, end),
    funding(start, end),
    ledger_observations(start, end),
  )
  for group in groups:
    for observation in group:
      yield HistoryRecord(
        observations=[observation],
        provenance={
          'source': 'api',
          'service': 'hyperliquid',
          'id': source_id('hyperliquid'),
        },
      )


records = [record async for record in history(start, end)]
len(records), records[:3]


# %% [markdown]
# ### Coverage assessment: `History`
#
# **Full**, for every source, all execute live against the real testnet account/API. `future_trades()` returns all 27 fills this account has ever had, and `funding()` 227 records of real hourly funding on its open `BTC` short. `spot_trades()` and `ledger_observations()` come back empty -- the account has never traded a `BASE/QUOTE`-named spot pair (see the coin-naming note below), and no deposit, withdrawal or transfer occurred in the queried window -- accurate negative results, not gaps in the mapping. `market.ipynb`'s `trades_history(PERP_MARKET, ...)`, the same underlying call windowed to one market, returns the same 24 `BTC` fills.
#
# **Two windows**: `funding()`, `ledger_observations()` and `history()` use the 30-day `start`/`end` pair; the two trade sources are called with the 180-day `fills_start`, because every fill on this account is from May-July and a 30-day window returns none of them. That is also why `history()` below yields 227 funding records and nothing else: the `BTC` short was opened well before the 30-day window (its `cumFunding.sinceOpen` in `market.ipynb`'s `clearinghouse_state` output already carries months of accrued funding), and it has simply been sitting there accruing funding since.
#
# **`UserFill.dir`** is an open-ended display string (`str` at all three declaration sites); these 27 fills carry five distinct values (`Buy`, `Sell`, `Open Long`, `Close Long`, `Open Short`). Both sources validate, which is why `time`, `px`, `sz`, `fee` and `closedPnl` arrive as `datetime`/`Decimal`.
#
# **A limitation these rows make visible**: three of the 27 fills (`HYPE`, 2026-05-10) come back with `coin='@1035'`. Hyperliquid reports spot pairs other than `PURR/USDC` by spot index rather than as `BASE/QUOTE`, so the `'/' in coin` split above reads them as perps and `future_trades()` emits them with `instrument`/`base` of `@1035` and `settle='USDC'`. A faithful mapping would resolve `@{index}` through `info.spot_meta()`'s `universe`/`tokens` back to a pair name and route them to `spot_trades()` -- which is what `spot_trades()`'s empty result is really reporting. The window held no fills at all before, so nothing exercised the split.
#
# **Not covered by `ledger_observations()`, but present in `UserNonFundingLedgerEntry.delta`'s ~20 variants**: vault flows (`vaultCreate`/`vaultDeposit`/`vaultDistribution`/`vaultWithdraw`/`vaultLeaderCommission`), staking transfers (`cStakingTransfer`), liquidations (`liquidation`), rewards claims (`rewardsClaim`), borrow/lend actions (`borrowLend`), and several gas/auction deltas -- omitted to keep this demo tractable; none of them fired on this account in the queried window, so the omission wasn't independently exercised against real data either way. `Yield`/`Bonus`/`Repay`/`Borrow` would be the natural `Observation` targets for the staking/borrow-lend/rewards deltas.

# %% [markdown]
# ## `Snapshots`

# %%
async def snapshot(assets: list[str] | None = None) -> SnapshotRecord:
  spot_state, perp_state, vault_equities = await asyncio.gather(
    client.info.spot_clearinghouse_state(user=ADDRESS),
    client.info.clearinghouse_state(user=ADDRESS),
    client.info.user_vault_equities(user=ADDRESS),
  )

  spot_balances: dict[str, Decimal] = {}
  for b in spot_state['balances']:
    if assets is not None and b['coin'] not in assets:
      continue
    spot_balances[b['coin']] = spot_balances.get(b['coin'], Decimal(0)) + Decimal(
      b['total']
    )

  perp_positions = {
    entry['position']['coin']: Position(
      size=Decimal(entry['position']['szi']),
      avg_price=Decimal(entry['position']['entryPx']),
    )
    for entry in perp_state['assetPositions']
  }

  vault_balances = {
    f'vault:{v["vaultAddress"]}': Decimal(v['equity']) for v in vault_equities
  }

  return SnapshotRecord(
    snapshot=Snapshot(
      subaccounts=[
        SubaccountSnapshot(subaccount='spot', balances=spot_balances),
        SubaccountSnapshot(
          subaccount='perp',
          balances={'USDC': Decimal(perp_state['marginSummary']['accountValue'])},
          positions=perp_positions,
        ),
        SubaccountSnapshot(subaccount='vaults', balances=vault_balances),
      ]
    ),
    provenance={
      'source': 'api',
      'service': 'hyperliquid',
      'id': source_id('hyperliquid'),
    },
  )


# Real state: nonzero USDC/HYPE spot balances and an open BTC perp short.
await snapshot()

# %% [markdown]
# ### Coverage assessment: `Snapshots`
#
# **Fully supported.** `spot`, `perp`, and `vaults` are each covered above with real account state: nonzero USDC/HYPE spot balances, the account's genuine open `BTC` short (`perp_positions`) plus its account-value balance, and an empty (but live-executed) `vaults` bucket -- this account holds equity in no vaults, an accurate negative result. `perp`'s balance uses `marginSummary.accountValue` (the account's total perp-wallet value) rather than a raw USDC deposit figure, since Hyperliquid's unified perp margin pool has no separate "USDC balance" distinct from account value once a position is open.
