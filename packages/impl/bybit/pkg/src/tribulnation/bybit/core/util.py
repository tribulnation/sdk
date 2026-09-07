"""Helpers for Bybit's wire quirks and window-capped history endpoints."""

from typing_extensions import Iterator, Literal
from datetime import datetime, timedelta
from decimal import Decimal

MILLISECOND = timedelta(milliseconds=1)
"""Bybit timestamps are epoch milliseconds, so this is one indivisible step."""

TRADE_WINDOW = timedelta(days=7)
"""Widest window `trade.trade_history` and `account.transaction_log` accept."""

RECORD_WINDOW = timedelta(days=30)
"""Widest window `asset.deposit.record` and `asset.withdraw.record` accept."""

SETTLE_COINS = ('USDT', 'USDC')
"""Settlement coins linear positions can be margined in.

`position.list` refuses to answer without a `settleCoin` (or a symbol), so every
account-wide sweep of open positions walks these in turn.
"""


def num(
  value: 'Literal[""] | Decimal | str | None', default: Decimal = Decimal(0)
) -> Decimal:
  """Read a Bybit numeric field, treating its empty-string sentinel as `default`.

  Bybit writes `''` instead of a number wherever a row means "nothing here" -- every
  numeric field of a coin the account has never held, and 22 fields of a flat position.
  A real `0` is a different thing and must survive, so this tests for the sentinel
  rather than for truthiness.
  """
  if value is None or value == '':
    return default
  return Decimal(value)


def windows(
  start: datetime, end: datetime, span: timedelta
) -> Iterator[tuple[datetime, datetime]]:
  """Split `[start, end]` into consecutive sub-windows of at most `span`.

  Bybit caps how wide a single history query may be -- 7 days for the transaction
  log and trade history, 30 for deposit and withdrawal records -- and rejects a
  wider one outright instead of truncating it.
  """
  lower = start
  while lower <= end:
    upper = min(lower + span, end)
    yield lower, upper
    lower = upper + MILLISECOND
