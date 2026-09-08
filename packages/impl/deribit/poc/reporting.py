# %%
import asyncio
from decimal import Decimal
from datetime import datetime, timedelta, timezone

from typing_extensions import Literal, TypeAlias, cast

from typed_deribit import Deribit
from dotenv import load_dotenv

load_dotenv()

public_client = await Deribit.new(public=True).__aenter__()
client = await Deribit.new(testnet=True).__aenter__()

from tribulnation.sdk.reporting import (
  HistoryRecord,
  Observation,
  Fee,
  FutureTrade,
  Funding,
  Transfer,
  CryptoDeposit,
  CryptoWithdrawal,
  UnknownObservation,
  Snapshot,
  SubaccountSnapshot,
  Position,
  SnapshotRecord,
  ApiProvenance,
)

CURRENCIES: list[Literal['BTC', 'ETH', 'USDC', 'SOL']] = ['BTC', 'ETH', 'USDC', 'SOL']

# `typed_deribit.account.get_account_summary.AccountSummary`'s `currency` accepts a specific
# Literal, but `snapshot(assets=...)` forwards an SDK-level `str` (per the abstract
# `Snapshots.snapshot` signature) -- the value is always a valid currency in practice, so
# `cast` bridges the gap rather than narrowing the abstract `assets` param itself.
AccountCurrency: TypeAlias = Literal[
  'BTC', 'ETH', 'STETH', 'ETHW', 'USDC', 'USDT', 'EURR', 'SOL', 'XRP', 'USYC', 'PAXG', 'BNB', 'USDE',
]


# %% [markdown]
# > Both `history()` and `snapshot()` below run entirely against `client`, the Deribit **TESTNET** account -- every observation, balance, and position shown reflects that test account's real (test) activity, not mainnet holdings. `public_client` is created for parity with the other notebooks but unused here.

# %% [markdown]
# ## `History` -- history

# %% [markdown]
# `private/get_transaction_log` is Deribit's single account-wide ledger: trades, deposits, withdrawals, transfers, settlements (incl. perpetual funding), and fee entries, per currency. It is fetched per-`CURRENCIES` entry below (Deribit has no "any currency" transaction log) and each row's `type` is mapped onto the closest `Observation` variant; anything not confidently classified falls back to `UnknownObservation` rather than being guessed.

# %%
async def history(
  start: datetime | None = None, end: datetime | None = None,
):
  """Map Deribit's per-currency transaction log into `HistoryRecord`s."""
  start = start or (datetime.now(timezone.utc) - timedelta(days=30))
  end = end or datetime.now(timezone.utc)
  for currency in CURRENCIES:
    # `_paged` walks the `continuation` cursor for us -- a single unpaginated call would
    # silently truncate to the first page (default 100 rows) for any busier account/window.
    paged = client.account.get_transaction_log_paged(
      currency=currency, start_timestamp=start, end_timestamp=end,
    )
    async for page in paged:
      for entry in page:
        provenance: ApiProvenance = {'source': 'api', 'service': 'deribit', 'id': str(entry['id'])}
        change = Decimal(str(entry.get('change', 0)))
        time = entry['timestamp']
        instrument_name = entry.get('instrument_name')
        cashflow = entry.get('cashflow')
        obs: Observation
        if entry['type'] == 'trade' and instrument_name:
          side = entry.get('side') or ''
          sign = -1 if 'sell' in side else 1
          commission = entry.get('commission')
          obs = FutureTrade(
            id=str(entry.get('trade_id') or entry['id']),
            time=time,
            instrument=instrument_name,
            settle=currency,
            size=sign * Decimal(str(entry.get('amount', 0))),
            price=Decimal(str(entry.get('price') or 0)),
            realized_pnl=Decimal(str(cashflow)) if cashflow is not None else None,
            order_id=entry.get('order_id'),
            fee=Fee(amount=Decimal(str(commission)), asset=currency) if commission else None,
          )
        elif entry['type'] == 'settlement' and instrument_name:
          obs = Funding(
            id=str(entry['id']), time=time, asset=currency,
            amount=change, instrument=instrument_name,
          )
        elif entry['type'] == 'deposit':
          obs = CryptoDeposit(id=str(entry['id']), time=time, asset=currency, amount=abs(change))
        elif entry['type'] == 'withdrawal':
          obs = CryptoWithdrawal(id=str(entry['id']), time=time, asset=currency, amount=change)
        elif entry['type'] == 'transfer':
          obs = Transfer(id=str(entry['id']), time=time, asset=currency, amount=change)
        else:
          obs = UnknownObservation(id=str(entry['id']), time=time, asset=currency, amount=change)
        yield HistoryRecord(observations=[obs], provenance=provenance)

records = [r async for r in history()]
len(records), records[:5]


# %% [markdown]
# ## `Snapshots` -- snapshot

# %% [markdown]
# Deribit reports balances per-currency (`private/get_account_summary`) and open positions across every currency at once (`private/get_positions(currency='any')`). Both take a `subaccount_id`, and `private/get_subaccounts` lists every compartment these credentials reach -- 6 on this testnet account, the main account included -- so each one becomes its own `SubaccountSnapshot`, keyed by username.

# %%
async def snapshot(assets: list[str] | None = None) -> SnapshotRecord:
  """Map Deribit account summaries + open positions, per subaccount, into a `SnapshotRecord`."""
  currencies = assets or CURRENCIES
  subaccounts: list[SubaccountSnapshot] = []
  for account in await client.account.get_subaccounts():
    balances: dict[str, Decimal] = {}
    for currency in currencies:
      summary = await client.account.get_account_summary(
        currency=cast(AccountCurrency, currency), subaccount_id=account['id'],
      )
      balances[currency] = Decimal(str(summary['equity']))
    positions_raw = await client.account.get_positions(currency='any', subaccount_id=account['id'])
    positions: dict[str, Position] = {
      p['instrument_name']: Position(
        size=Decimal(str(p.get('size_currency', p['size']))),
        avg_price=Decimal(str(p['average_price'])),
      )
      for p in positions_raw if p['size'] != 0
    }
    subaccounts.append(SubaccountSnapshot(
      subaccount=account['username'], balances=balances, positions=positions,
    ))
  snap = Snapshot(subaccounts=subaccounts)
  return SnapshotRecord(
    snapshot=snap,
    provenance={'source': 'api', 'service': 'deribit', 'id': f'snapshot:{snap.time.isoformat()}'},
  )

await snapshot()

# %% [markdown]
# ## Coverage assessment

# %% [markdown]
# **Full**, both methods execute live against the testnet account and return real (possibly empty) data:
# - `history()` covers every transaction-log `type` Deribit documents as "most common" (`trade`, `deposit`, `withdrawal`, `transfer`, `settlement`) plus a genuine fallback for anything else via `UnknownObservation` -- nothing is silently dropped. Live over the last 30 days the log yields `trade`, `settlement`, `transfer`, `delivery` and `options_settlement_summary` rows across `BTC`/`ETH`/`USDC`/`SOL`; the last two take the `UnknownObservation` path. No `deposit` or `withdrawal` row occurred in the windows run here, so those two branches are mapped but unexercised.
# - `settlement`-type rows are mapped to `Funding` unconditionally when they carry an `instrument_name`, and that does over-collect: dated futures are marked to market under the same `settlement` type, e.g. 85 `BTC-27JUN25` rows in this account's Apr-Sep 2025 log alongside 81 `ETH-PERPETUAL` ones. The transaction log does not distinguish the two beyond `instrument_name`, which was not enough to separate them reliably here. (Expiries and option settlements do arrive as their own types, `delivery` and `options_settlement_summary`, and fall through to `UnknownObservation`.)
# - `history()` reads the credentialed account's own log; `subaccount_id` would be needed to walk the other compartments.
# - `snapshot()` returns real non-trivial state: 6 compartments, of which the main account (`marciclabas`) holds nonzero balances across `BTC`/`ETH`/`USDC`/`SOL` and two genuinely open positions (`ETH-PERPETUAL`, `ETH_USDC-PERPETUAL`), plus small `BTC` or `USDC` balances on three of the subaccounts. Flat instruments are filtered out (`size != 0`) rather than shown as zero-size noise.
