"""Public funding-rate history and the account's own funding settlements."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing_extensions import AsyncIterator, Sequence

from tribulnation.sdk.core import ApiError, PaginatedResponse
from tribulnation.sdk.market import FundingPayment, FundingRate
from .common import Shared

FUNDING_WINDOW = timedelta(days=1)
"""Funding history window: at most 24 hourly settlements, within one page."""
FUNDING_PAGE = 100
"""Settlements requested per funding page."""


def rates(
  shared: Shared, symbol: str, start: datetime | None, end: datetime | None
) -> PaginatedResponse[FundingRate]:
  """Page settled funding with inclusive bounds and an untruncated open start."""
  lower = start if start is not None else datetime(1970, 1, 1, tzinfo=timezone.utc)
  upper = end if end is not None else datetime.now(timezone.utc)
  if lower.utcoffset() is None or upper.utcoffset() is None or upper < lower:
    raise ValueError('Funding bounds must be aware and end must not precede start')

  async def pages():
    """Retry each native page independently and filter inclusive SDK bounds."""
    source = shared.client.futures.funding_fees.public_funding_history_paged(
      symbol,
      from_=lower,
      to=upper,
    ).via(shared.call)
    async for page in source:
      yield [
        FundingRate(time=r['timepoint'], rate=Decimal(str(r['fundingRate'])))
        for r in page
        if lower <= r['timepoint'] <= upper
      ]

  return PaginatedResponse(pages())


def payments(
  shared: Shared, symbol: str, start: datetime, end: datetime
) -> PaginatedResponse[FundingPayment]:
  """The account's settled funding on one contract, positive when received."""
  if start.utcoffset() is None or end.utcoffset() is None:
    raise ValueError('Funding history bounds must be timezone-aware')
  return PaginatedResponse(payment_pages(shared, symbol, start, end))


async def payment_pages(
  shared: Shared, symbol: str, start: datetime, end: datetime
) -> AsyncIterator[Sequence[FundingPayment]]:
  """One request per one-day window up to now, each retried on its own.

  Raises:
    ApiError: A one-day window holds more settlements than one page.
  """
  lower = start
  horizon = min(end, datetime.now(timezone.utc))
  while lower <= horizon:
    upper = min(lower + FUNDING_WINDOW - timedelta(milliseconds=1), horizon)
    page = await shared.call(
      lambda: shared.client.futures.funding_fees.private_funding_history(
        symbol, start_at=lower, end_at=upper, max_count=FUNDING_PAGE
      )
    )
    if page['hasMore']:
      raise ApiError('KuCoin funding history holds more than a page in one day')
    if rows := [
      FundingPayment(amount=Decimal(str(r['funding'])), time=r['timePoint'])
      for r in page['dataList']
      if lower <= r['timePoint'] <= upper
    ]:
      yield rows
    lower = upper + timedelta(milliseconds=1)
