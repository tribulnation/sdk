"""Account-wide Deribit ledger and snapshots without fixed currency lists."""

from datetime import datetime, timedelta, timezone
from asyncio import sleep
from decimal import Decimal
from typing_extensions import AsyncIterator, Collection

from typed_deribit.account.get_transaction_log import TransactionLogEntry
from typed_deribit.schemas import Position as RawPosition
from tribulnation.sdk.reporting import (
  CryptoDeposit,
  CryptoWithdrawal,
  HistoryRecord,
  Observation,
  Position,
  Report as BaseReport,
  Snapshot,
  SnapshotRecord,
  SubaccountSnapshot,
  Transfer,
  UnknownObservation,
  source_id,
)
from .core import Mixin


def parse_entry(entry: TransactionLogEntry) -> HistoryRecord:
  """Preserve ledger balance changes, classifying only unambiguous cash movements.

  Settlement combines session PnL and funding; it is not itself a funding payment.
  Trades include options premiums, so they cannot all be labelled futures fills.
  Those rows remain unknown observations until a dedicated economic mapping exists.
  """
  if entry['type'] == 'deposit' and entry['change'] >= 0:
    cls = CryptoDeposit
  elif entry['type'] == 'withdrawal':
    cls = CryptoWithdrawal
  elif entry['type'] == 'transfer':
    cls = Transfer
  else:
    cls = UnknownObservation
  observation: Observation = cls(
    id=str(entry['id']),
    time=entry['timestamp'],
    asset=entry['currency'],
    amount=Decimal(str(entry['change'])),
    subaccount=str(entry['user_id']),
  )
  return HistoryRecord(
    observations=[observation],
    provenance={
      'source': 'api',
      'service': 'deribit',
      'id': f'ledger:{entry["user_id"]}:{entry["currency"]}:{entry["id"]}',
    },
  )


def parse_position(row: RawPosition) -> Position:
  """Use base units and the explicit direction, including short positions."""
  quantity = row.get('size_currency')
  if quantity is None:
    if row['kind'] != 'option':
      raise ValueError('Deribit futures position omitted its base-unit size')
    quantity = row['size']
  size = abs(Decimal(str(quantity)))
  if row['direction'] == 'sell':
    size = -size
  return Position(size=size, avg_price=Decimal(str(row['average_price'])))


class Report(Mixin, BaseReport):
  """Read all accessible compartments; API retention remains best-effort."""

  async def history(
    self,
    start: datetime | None = None,
    end: datetime | None = None,
  ) -> AsyncIterator[HistoryRecord]:
    """Walk each discovered currency's ledger for every accessible subaccount.

    Omitted bounds select the last 30 days. Current currency discovery cannot find
    assets the venue has completely removed; file ingestion covers such gaps.
    """
    end = end or datetime.now(timezone.utc)
    start = start or end - timedelta(days=30)
    if start.utcoffset() is None or end.utcoffset() is None:
      raise ValueError('History bounds must be timezone-aware')
    if start > end:
      raise ValueError('History start must not follow end')
    currencies = await self.call(self.client.market_data.get_currencies)
    accounts = await self.call(self.client.account.get_subaccounts)
    requested = False
    for account in accounts:
      for currency in currencies:
        continuation = None
        seen: set[int] = set()
        cursors: set[int] = set()
        while True:
          # This endpoint has its own one-request-per-second budget, independent
          # of the general account API budget. Pace this sweep, including pages.
          if requested:
            await sleep(1)
          requested = True
          page = await self.call(
            lambda: self.client.account.get_transaction_log(
              currency=currency['currency'],
              start_timestamp=start,
              end_timestamp=end,
              subaccount_id=account['id'],
              count=250,
              continuation=continuation,
            )
          )
          for entry in page['logs']:
            if entry['id'] not in seen and start <= entry['timestamp'] <= end:
              seen.add(entry['id'])
              yield parse_entry(entry)
          continuation = page.get('continuation')
          if continuation is None or continuation in cursors:
            break
          cursors.add(continuation)

  async def snapshot(self, assets: Collection[str] | None = None) -> SnapshotRecord:
    """Read native balances and base-unit positions, not equity counted twice."""
    accounts = await self.call(self.client.account.get_subaccounts)
    states: list[SubaccountSnapshot] = []
    for account in accounts:
      summaries = await self.call(
        lambda: self.client.account.get_account_summaries(
          subaccount_id=account['id'],
        )
      )
      rows = await self.call(
        lambda: self.client.account.get_positions(
          currency='any',
          subaccount_id=account['id'],
        )
      )
      states.append(
        SubaccountSnapshot(
          subaccount=str(account['id']),
          balances={
            row['currency']: Decimal(str(row['balance']))
            for row in summaries['summaries']
            if assets is None or row['currency'] in assets
          },
          positions={
            row['instrument_name']: parse_position(row)
            for row in rows
            if row['size'] != 0
          },
        )
      )
    return SnapshotRecord(
      snapshot=Snapshot(subaccounts=states),
      provenance={'source': 'api', 'service': 'deribit', 'id': source_id('deribit')},
    )
