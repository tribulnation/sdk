"""Binance transaction history, merged from every account-scoped source."""

from typing_extensions import AsyncIterable, AsyncIterator
from dataclasses import dataclass
from datetime import datetime

from tribulnation.sdk.core import SDK, AuthError
from tribulnation.sdk.reporting import History as _History, HistoryRecord

from ..util import new_source_id, raise_if_all_failed
from .spot import SpotHistory
from .usdm import UsdmHistory


@dataclass
class History(SpotHistory, UsdmHistory, _History):
  """Binance transaction history.

  Six sources, none of which Binance unifies for you: spot fills, on-chain deposits,
  on-chain withdrawals, wallet-to-wallet transfers, USD-M futures fills, and the USD-M
  income ledger.

  **Does not support**:
  - Margin borrow/repay and margin fills (`spot.http.margin`).
  - COIN-M futures, Options and Portfolio Margin, each of which has its own parallel
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
    """Stream this account's history over an explicit window.

    Both bounds are required: no Binance history endpoint serves all time, and each one
    stops at a different retention horizon (90 days for deposits/withdrawals, three
    months for USD-M income, six months for transfers and fills), so an open-ended
    window would silently return a truncated result rather than everything.

    A source that raises `AuthError` is reported as a permission gap and skipped -- the
    API key's Futures, Margin and Options permissions are separate flags -- unless every
    source raises one, which means the credentials themselves are bad.
    """
    if start is None or end is None:
      raise ValueError('Binance history requires both start and end.')
    id = new_source_id()
    sources: list[AsyncIterable[HistoryRecord]] = [
      self.crypto_deposits(start, end, id=id),
      self.crypto_withdrawals(start, end, id=id),
      self.internal_transfers(start, end, id=id),
      self.income(start, end, id=id),
    ]
    if self.spot_markets:
      sources.append(self.spot_trades(start, end, id=id))
    if self.usdm_markets:
      sources.append(self.future_trades(start, end, id=id))

    failures: list[AuthError] = []
    for source in sources:
      try:
        async for entry in source:
          yield entry
      except AuthError as e:
        failures.append(e)
    raise_if_all_failed(failures, len(sources))
