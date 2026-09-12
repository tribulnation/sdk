"""Binance transaction history, limited to the declared spot-side sources."""

from typing_extensions import AsyncIterable, AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from tribulnation.sdk.core import SDK
from tribulnation.sdk.reporting import History as _History, HistoryRecord

from ..util import months_before, new_source_id
from .spot import SpotHistory


@dataclass
class History(SpotHistory, _History):
  """Binance transaction history.

  Spot fills, on-chain deposits/withdrawals and transfers between Spot and Funding.
  Futures endpoints are never called; their absence is explicit scope, not zero exposure.

  **Does not support**:
  - Margin borrow/repay and margin fills (`spot.http.margin`).
  - USD-M and COIN-M futures, Options and Portfolio Margin, each of which has its own parallel
    fills/income surface.
  - Simple Earn subscription, redemption and reward events
    (`simple_earn.*.history`) -- the Earn surface reports the current product
    catalogue, not a dated ledger.
  - Convert, C2C, Pay, Fiat, NFT and Mining, each with its own account-scoped history.
  """

  @SDK.method
  async def history(
    self, start: datetime | None = None, end: datetime | None = None
  ) -> AsyncIterator[HistoryRecord]:
    """Stream best-effort history without requiring dates or a list of traded markets.

    An omitted end means now. With no start, capital uses the preceding 90 days,
    Spot/Funding transfers six calendar months.
    Spot fills walk the retained ID history for every discoverable symbol. Explicit
    bounds are preserved; venue retention and delisted symbols can still leave gaps.

    Errors from supported sources propagate; rejected reads are not empty history.
    """
    end = end if end is not None else datetime.now(timezone.utc)
    if end.utcoffset() is None or (start is not None and start.utcoffset() is None):
      raise ValueError('Binance history bounds must be timezone-aware.')
    if start is not None and start > end:
      raise ValueError('Binance history start must not follow end.')
    capital_start = start if start is not None else end - timedelta(days=90)
    transfer_start = start if start is not None else months_before(end, 6)
    id = new_source_id()
    sources: list[AsyncIterable[HistoryRecord]] = [
      self.crypto_deposits(capital_start, end, id=id),
      self.crypto_withdrawals(capital_start, end, id=id),
      self.internal_transfers(transfer_start, end, id=id),
      self.spot_trades(start, end, id=id),
    ]

    for source in sources:
      async for entry in source:
        yield entry
