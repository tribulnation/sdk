"""Kucoin Classic spot-side reporting with automatic discovery and best-effort history."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing_extensions import AsyncIterator, Collection
from typed_kucoin.schemas import HfFill
from tribulnation.sdk.reporting import (
  CryptoDeposit,
  CryptoWithdrawal,
  Fee,
  HistoryRecord,
  Observation,
  Report as BaseReport,
  Snapshot,
  SnapshotRecord,
  SpotTrade,
  SubaccountSnapshot,
  Transfer,
  source_id,
)
from .core import Mixin


def record(observation: Observation, kind: str) -> HistoryRecord:
  """Scope provenance by source and native row id."""
  return HistoryRecord(
    observations=[observation],
    provenance={
      'source': 'api',
      'service': 'kucoin',
      'id': f'{kind}:{observation.id}',
    },
  )


def parse_spot(row: HfFill) -> SpotTrade:
  """Read the traded symbol from the fill, including previously held assets."""
  base, quote = row['symbol'].split('-', 1)
  return SpotTrade(
    id=str(row['tradeId']),
    time=row['createdAt'],
    subaccount='trade',
    base=base,
    quote=quote,
    pair=row['symbol'],
    order_id=row['orderId'],
    size=row['size'] if row['side'] == 'buy' else -row['size'],
    price=row['price'],
    fee=Fee(amount=row['fee'], asset=row['feeCurrency']),
  )


class Report(Mixin, BaseReport):
  """Classic spot-side history and snapshots; futures are explicitly out of scope."""

  async def spot_trades(
    self, start: datetime, end: datetime
  ) -> AsyncIterator[HistoryRecord]:
    """Sweep every symbol once, paginating the requested interval.

    The endpoint applies its own retention fallback. Splitting an older interval
    into seven-day windows repeats the retained data instead of extending backfill.

    References:
      - https://www.kucoin.com/docs-new/rest/spot-trading/orders/get-trade-history
    """
    symbols = await self.call(self.client.spot.all_symbols)
    for symbol in symbols:
      seen: set[int] = set()
      cursor = None
      cursors: set[int] = set()
      while True:
        page = await self.call(
          lambda: self.client.spot.orders_hf.get_trade_history(
            symbol=symbol['symbol'],
            start_at=start,
            end_at=end,
            last_id=cursor,
            limit=100,
          )
        )
        for row in page['items']:
          if row['id'] not in seen and start <= row['createdAt'] <= end:
            seen.add(row['id'])
            yield record(parse_spot(row), f'spot:{row["symbol"]}')
        cursor = page['lastId']
        if not cursor or cursor in cursors:
          break
        cursors.add(cursor)

  async def capital(
    self, start: datetime, end: datetime
  ) -> AsyncIterator[HistoryRecord]:
    """Walk account-wide completed movements, preserving internal transfers too."""
    for withdrawal in (False, True):
      source = (
        self.client.account.withdrawals if withdrawal else self.client.account.deposit
      )
      number = 1
      seen: set[str] = set()
      while True:
        page = await self.call(
          lambda: source.history(
            start_at=start,
            end_at=end,
            status='SUCCESS',
            current_page=number,
            page_size=100,
          )
        )
        for row in page['items']:
          if row['id'] in seen or not start <= row['createdAt'] <= end:
            continue
          seen.add(row['id'])
          fee = Fee(amount=row['fee'], asset=row['currency'])
          observation: Observation
          if row['isInner']:
            observation = Transfer(
              id=row['id'],
              time=row['createdAt'],
              subaccount='main',
              asset=row['currency'],
              amount=-abs(row['amount']) if withdrawal else abs(row['amount']),
              fee=fee,
            )
          else:
            cls = CryptoWithdrawal if withdrawal else CryptoDeposit
            observation = cls(
              id=row['id'],
              time=row['createdAt'],
              subaccount='main',
              asset=row['currency'],
              amount=row['amount'],
              fee=fee,
              network=row['chain'] or None,
              tx_id=row['walletTxId'],
              dst_address=row['address'] or None,
            )
          yield record(observation, 'withdrawal' if withdrawal else 'deposit')
        if not page['items'] or number >= page['totalPage']:
          break
        number += 1

  async def history(
    self,
    start: datetime | None = None,
    end: datetime | None = None,
  ) -> AsyncIterator[HistoryRecord]:
    """Default to seven days of retained spot fills and 30 days of capital history."""
    end = end or datetime.now(timezone.utc)
    lower = start or end - timedelta(days=30)
    if lower.utcoffset() is None or end.utcoffset() is None:
      raise ValueError('History bounds must be timezone-aware')
    if lower > end:
      raise ValueError('History start must not follow end')
    for source in (
      self.capital(lower, end),
      self.spot_trades(start or end - timedelta(days=7), end),
    ):
      async for row in source:
        yield row

  async def snapshot(self, assets: Collection[str] | None = None) -> SnapshotRecord:
    """Read main/trade and Earn balances only; rejected reads are not zero balances."""
    states: dict[str, SubaccountSnapshot] = {}
    for row in await self.call(self.client.account.spot_accounts):
      if row['type'] not in ('main', 'trade'):
        continue
      if assets is None or row['currency'] in assets:
        state = states.setdefault(
          row['type'], SubaccountSnapshot(subaccount=row['type'])
        )
        state.balances[row['currency']] = (
          state.balances.get(row['currency'], Decimal(0)) + row['balance']
        )
    earn = SubaccountSnapshot(subaccount='earn')
    number = 1
    while True:
      page = await self.call(
        lambda: self.client.earn.account_holding(current_page=number, page_size=100)
      )
      for row in page['items']:
        if assets is None or row['currency'] in assets:
          earn.balances[row['currency']] = (
            earn.balances.get(row['currency'], Decimal(0))
            + row['holdAmount']
            + row['redeemingAmount']
          )
      if not page['items'] or number >= page['totalPage']:
        break
      number += 1
    states['earn'] = earn
    return SnapshotRecord(
      snapshot=Snapshot(subaccounts=list(states.values())),
      provenance={'source': 'api', 'service': 'kucoin', 'id': source_id('kucoin')},
    )
