"""Personal fills and funding payments, and public candles.

Fill history comes from `userFillsByTime` with `startTime` only: the venue returns the
newest fills at or after it, newest first, at most 10,000. Its `endTime` is honored only
for recent fills (archived ranges ignore it), so it is not sent; the upper bound is
applied locally. A full response whose oldest fill is still after `start` means older
fills in the range were cut off, and the walk raises rather than returning a partial
history.
"""

from datetime import datetime

from typing_extensions import AsyncIterable, Sequence
from tribulnation.sdk.core import ApiError
from tribulnation.sdk.market import (
  Candle,
  CandleInterval,
  ExchangeFundingPayment,
  ExchangeTrade,
  FundingPayment,
  Trade,
  candle_windows,
)

from ..core import Shared
from .common import parse_candle, parse_fill

FILLS_CAP = 10_000
"""Most fills `userFills`/`userFillsByTime` return (measured: exactly 10,000)."""
CANDLES_WINDOW = 5_000
"""Candles requested per window. No cap was observed (14,401 one-minute candles in one
response); windows keep each response bounded."""
CANDLE_INTERVALS = frozenset[CandleInterval]({'1m', '5m', '15m', '1h', '4h', '1d'})
"""Every contract interval is one of the venue's own."""


def is_perp(coin: str) -> bool:
  """Whether a fill or funding row belongs to a perpetual (spot pairs read `BASE/QUOTE`)."""
  return '/' not in coin


async def trades_history(
  shared: Shared, coin: str | None, start: datetime, end: datetime
) -> AsyncIterable[Sequence[Trade]]:
  """Perpetual fills with `start <= time <= end`, newest first; exchange-wide rows are
  `ExchangeTrade`s.

  Raises:
    ApiError: More than 10,000 fills fall between `start` and now, so the venue cut off
      the oldest ones in range.
  """
  user = shared.user
  fills = await shared.call(
    lambda: shared.client.info.user_fills_by_time(user, start_time=start)
  )
  if len(fills) >= FILLS_CAP and fills[-1]['time'] > start:
    raise ApiError(
      f'Margin Trade returned its {FILLS_CAP} newest fills since {start.isoformat()}, ending at '
      f'{fills[-1]["time"].isoformat()}; older fills in the range are not reachable. Narrow `start`.'
    )
  rows: list[Trade] = []
  for f in fills:
    if (
      start <= f['time'] <= end
      and is_perp(f['coin'])
      and (coin is None or f['coin'] == coin)
    ):
      trade = parse_fill(f)
      rows.append(
        trade if coin is not None else ExchangeTrade(**vars(trade), market_id=f['coin'])
      )
  if rows:
    yield rows


async def funding_payments(
  shared: Shared, coin: str | None, start: datetime, end: datetime
) -> AsyncIterable[Sequence[FundingPayment]]:
  """Funding payments with `start <= time <= end`, received-positive (the venue's `usdc`
  is already negative when paid). The venue returned every row in one response in all
  measurements (about 20,000 rows); there is no cursor to page with."""
  user = shared.user
  rows = await shared.call(
    lambda: shared.client.info.user_funding(user, start_time=start, end_time=end)
  )
  page: list[FundingPayment] = []
  for r in rows:
    delta = r['delta']
    if start <= r['time'] <= end and (coin is None or delta['coin'] == coin):
      if coin is None:
        page.append(
          ExchangeFundingPayment(
            amount=delta['usdc'], time=r['time'], market_id=delta['coin']
          )
        )
      else:
        page.append(FundingPayment(amount=delta['usdc'], time=r['time']))
  if page:
    yield page


async def candles(
  shared: Shared, coin: str, interval: CandleInterval, start: datetime, end: datetime
) -> AsyncIterable[Sequence[Candle]]:
  """Candles opening in `[start, end)`, ascending, one request per window. The venue's
  bounds are inclusive at both ends, so the window's upper candle is dropped locally."""
  for lower, upper in candle_windows(start, end, interval, size=CANDLES_WINDOW):
    response = await shared.call(
      lambda: shared.client.info.candle_snapshot(
        coin, interval=interval, start_time=lower, end_time=upper
      )
    )
    rows = [parse_candle(c) for c in response if lower <= c['t'] < upper]
    if rows:
      yield rows
