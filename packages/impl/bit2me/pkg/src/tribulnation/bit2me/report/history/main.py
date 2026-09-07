"""Bit2Me implementation of the `history` reporting endpoint."""

from typing_extensions import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import asyncio

from tribulnation.sdk.reporting import (
  History as _History,
  HistoryRecord,
  Observation,
  source_id,
)

from .earn import EarnYields
from .trades import SpotTrades
from .transactions import CryptoTransfers

GENESIS = datetime(2015, 1, 1, tzinfo=timezone.utc)
"""Earliest time worth asking Bit2Me about -- the venue launched in 2014, so no
account predates this. Used when a caller asks for history with no `start`."""


@dataclass(frozen=True, kw_only=True)
class History(_History, SpotTrades, CryptoTransfers, EarnYields):
  """Bit2Me implementation of `History`.

  No Bit2Me endpoint is a unified ledger, so this composes three separately-shaped
  sources, each with an unambiguous `Observation` mapping: Trading Spot fills,
  on-chain deposits and withdrawals, and Earn reward payouts.

  Deliberately unmapped, and why:

  - **Internal transfers** between the spot, earn and pocket compartments. They are
    reachable (`v3/wallet/transaction`'s `deposit-earn`/`withdrawal-trading`/...
    operations) and would map to `InternalTransfer`, but their semantics are not
    what the PoC confirmed end to end.
  - **Fiat deposits and withdrawals**. `operation='withdrawal'` returns the fiat
    bank rows, but the matching fiat *deposit* (`subtype='funding'`) is returned by
    no `operation` value at all -- it only shows up in the unfiltered listing -- so
    the fiat side cannot be enumerated symmetrically.
  - **Loans** (`v1/loan/*`) and **Social Pay** (`v1/social-pay/*`), separate ledgers.
  """

  async def history(
    self, start: datetime | None = None, end: datetime | None = None
  ) -> AsyncIterator[HistoryRecord]:
    """Stream the account's history as one record per observation.

    Args:
      start: Start of the window (inclusive). `None` reads from `GENESIS`.
      end: End of the window (inclusive). `None` reads through now.
    """
    end = end or datetime.now(timezone.utc)
    start = start or GENESIS
    groups: Sequence[Sequence[Observation]] = await asyncio.gather(
      self.spot_trades(start, end),
      self.crypto_deposits(start, end),
      self.crypto_withdrawals(start, end),
      self.earn_yields(start, end),
    )
    for group in groups:
      for observation in group:
        yield HistoryRecord(
          observations=[observation],
          provenance={'source': 'api', 'service': 'bit2me', 'id': source_id('bit2me')},
        )
