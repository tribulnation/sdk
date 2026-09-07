"""Bybit's account history, as a stream of `HistoryRecord`s.

Four sources feed it: spot fills, linear funding settlements, and crypto deposits
and withdrawals. Every page of every one of them is fetched through `call_bybit`,
so a throttled page retries in place instead of restarting the sweep.
"""

from typing_extensions import AsyncIterator
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from tribulnation.sdk.reporting import (
  ApiProvenance,
  CryptoDeposit,
  CryptoWithdrawal,
  Fee,
  Funding,
  HistoryRecord,
  SpotTrade,
)

from tribulnation.bybit.core import RECORD_WINDOW, TRADE_WINDOW, Mixin, windows

SERVICE = 'typed_bybit'
"""`ApiProvenance.service` for every record this module emits."""

RETENTION = timedelta(days=730)
"""How far back Bybit serves history; it refuses a window starting earlier outright."""


def bounds(start: datetime | None, end: datetime | None) -> tuple[datetime, datetime]:
  """Resolve an open-ended window against Bybit's own retention limit."""
  resolved_end = end or datetime.now(timezone.utc)
  return start or resolved_end - RETENTION, resolved_end


async def spot_trades(
  self: Mixin, start: datetime, end: datetime
) -> AsyncIterator[HistoryRecord]:
  """Yield one record per spot fill in the window."""
  for lower, upper in windows(start, end, TRADE_WINDOW):
    cursor: str | None = None
    while True:
      page = await self.call_bybit(
        lambda: self.client.trade.trade_history(
          'spot',
          start_time=lower,
          end_time=upper,
          exec_type='Trade',
          cursor=cursor,
          validate=self.validate,
        )
      )
      for t in page['list']:
        qty = t['execQty']
        yield HistoryRecord(
          observations=[
            SpotTrade(
              id=t['execId'],
              time=t['execTime'],
              pair=t['symbol'],
              size=qty if t['side'] == 'Buy' else -qty,
              price=t['execPrice'],
              order_id=t['orderId'],
              # `execFee` is required and already a `Decimal`. A zero fee is a real
              # fee -- 40 of the 55 spot fills on the account this was derived
              # against carry exactly `0` -- so it is never guarded away as absent.
              fee=Fee(amount=t['execFee'], asset=t['feeCurrency']),
            )
          ],
          provenance=ApiProvenance(
            id=f'spot-trade-{t["execId"]}', source='api', service=SERVICE
          ),
        )
      cursor = page.get('nextPageCursor')
      if not cursor:
        break


async def funding_settlements(
  self: Mixin, start: datetime, end: datetime
) -> AsyncIterator[HistoryRecord]:
  """Yield one record per linear funding settlement in the window."""
  for lower, upper in windows(start, end, TRADE_WINDOW):
    cursor: str | None = None
    while True:
      page = await self.call_bybit(
        lambda: self.client.account.transaction_log(
          category='linear',
          type='SETTLEMENT',
          start_time=lower,
          end_time=upper,
          cursor=cursor,
          validate=self.validate,
        )
      )
      for e in page['list']:
        # `funding` is `NotRequired`; `'funding' in e` is what narrows it away, since
        # a truthiness check on `.get()` does not.
        if 'funding' not in e or not e['funding']:
          continue
        yield HistoryRecord(
          observations=[
            Funding(
              time=e['transactionTime'],
              amount=Decimal(e['funding']),
              asset=e['currency'],
              instrument=e['symbol'] or None,
            )
          ],
          provenance=ApiProvenance(
            id=f'funding-{e["id"]}', source='api', service=SERVICE
          ),
        )
      cursor = page.get('nextPageCursor')
      if not cursor:
        break


async def deposits(
  self: Mixin, start: datetime, end: datetime
) -> AsyncIterator[HistoryRecord]:
  """Yield one record per on-chain deposit in the window."""
  for lower, upper in windows(start, end, RECORD_WINDOW):
    paging = self.client.asset.deposit.record_paged(
      start_time=lower, end_time=upper, validate=self.validate
    )
    state: str | None = paging.init
    while state is not None:
      # Pyright does not carry the `while` narrowing into the closure, and the lambda
      # runs inside this same `await`, before `state` is reassigned.
      chunk, state = await self.call_bybit(lambda: paging.next(state))  # type: ignore
      for d in chunk:
        fee = d['depositFee']
        yield HistoryRecord(
          observations=[
            CryptoDeposit(
              id=d['id'],
              time=d['successAt'],
              amount=d['amount'],
              asset=d['coin'],
              network=d['chain'],
              tx_id=d['txID'] or None,
              dst_address=d['toAddress'] or None,
              # `''` is Bybit's "no fee charged" sentinel here, and every deposit on
              # the account this was derived against carries it.
              fee=None if fee == '' else Fee(amount=fee, asset=d['coin']),
            )
          ],
          provenance=ApiProvenance(
            id=f'deposit-{d["id"]}', source='api', service=SERVICE
          ),
        )


async def withdrawals(
  self: Mixin, start: datetime, end: datetime
) -> AsyncIterator[HistoryRecord]:
  """Yield one record per withdrawal in the window."""
  for lower, upper in windows(start, end, RECORD_WINDOW):
    paging = self.client.asset.withdraw.record_paged(
      start_time=lower, end_time=upper, validate=self.validate
    )
    state: str | None = paging.init
    while state is not None:
      chunk, state = await self.call_bybit(lambda: paging.next(state))  # type: ignore
      for w in chunk:
        yield HistoryRecord(
          observations=[
            CryptoWithdrawal(
              id=w['withdrawId'],
              time=w['updateTime'],
              amount=Decimal(w['amount']),
              asset=w['coin'],
              network=w['chain'],
              tx_id=w['txID'] or None,
              dst_address=w['toAddress'] or None,
              # Required and always present; `'0'` is a free withdrawal, not a
              # missing one, so it is reported rather than guarded away.
              fee=Fee(amount=Decimal(w['withdrawFee']), asset=w['coin']),
            )
          ],
          provenance=ApiProvenance(
            id=f'withdrawal-{w["withdrawId"]}', source='api', service=SERVICE
          ),
        )


async def history(
  self: Mixin, start: datetime | None = None, end: datetime | None = None
) -> AsyncIterator[HistoryRecord]:
  """Stream spot fills, funding settlements, deposits and withdrawals in the window."""
  lower, upper = bounds(start, end)
  async for record in spot_trades(self, lower, upper):
    yield record
  async for record in funding_settlements(self, lower, upper):
    yield record
  async for record in deposits(self, lower, upper):
    yield record
  async for record in withdrawals(self, lower, upper):
    yield record
