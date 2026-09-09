"""Kraken implementation of the `history` reporting endpoint, over `Ledgers`.

Kraken has no unified history endpoint, but its ledger is close: every balance-affecting
event -- trades, deposits, withdrawals, staking rewards, transfers -- is one row per
asset leg, which is the SDK's per-observation model. A spot trade is therefore two
ledger rows (base leg and quote leg) sharing a `refid`, and each row becomes its own
record here rather than being joined back into one `SpotTrade`: that join would need
`TradesHistory` for the price and side, and the ledger row is the source this surface
transcribes.
"""

from typing_extensions import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from tribulnation.sdk.reporting import (
  Bonus,
  CryptoDeposit,
  CryptoWithdrawal,
  FeeLeg,
  FiatDeposit,
  FiatWithdrawal,
  History as _History,
  HistoryRecord,
  TradeLeg,
  Transfer,
  UnknownObservation,
  Yield,
)
from tribulnation.kraken.core import Mixin

from typed_kraken.spot.account.ledgers import LedgerEntry

LEDGER_PAGE = 50
"""Rows per page. `Ledgers` serves 50 at a time, newest first."""

FIAT_ASSETS = frozenset(
  {'ZUSD', 'ZEUR', 'ZGBP', 'ZCAD', 'ZJPY', 'ZAUD', 'ZKRW', 'CHF', 'MXN', 'BRL'}
)
"""Kraken's fiat balances: the `Z`-prefixed legacy ids plus the newer bare ones. The
asset catalogue classes fiat and crypto alike as `currency`, so there is no field to
read this off."""

LedgerObservation = (
  TradeLeg
  | FiatDeposit
  | CryptoDeposit
  | FiatWithdrawal
  | CryptoWithdrawal
  | Yield
  | Transfer
  | Bonus
  | UnknownObservation
  | FeeLeg
)
"""The observation shapes a ledger row can produce."""


def parse_entry(ledger_id: str, entry: LedgerEntry) -> Sequence[LedgerObservation]:
  """Map one ledger row onto its observations: the row's own, plus a fee leg when
  the row bundles a non-zero fee.

  Only the common ledger types get a precise shape; `margin`, `adjustment`,
  `rollover`, `settled`, `sale`, `conversion`, the `nft*` types and the rest fall
  through to `UnknownObservation` rather than guessing at their semantics.

  Args:
    ledger_id: The row's ledger id, the key it is listed under.
    entry: The row.
  """
  asset = entry.get('asset', '')
  amount = entry.get('amount', Decimal(0))
  time = entry.get('time')
  kind = entry.get('type')
  fiat = asset in FIAT_ASSETS

  first: LedgerObservation
  if kind == 'trade':
    first = TradeLeg(
      id=ledger_id,
      time=time,
      asset=asset,
      amount=amount,
      trade_id=entry.get('refid'),
      event_type='spot_trade',
      label=entry.get('subtype') or None,
    )
  elif kind == 'deposit':
    cls = FiatDeposit if fiat else CryptoDeposit
    first = cls(id=ledger_id, time=time, asset=asset, amount=abs(amount))
  elif kind == 'withdrawal':
    cls = FiatWithdrawal if fiat else CryptoWithdrawal
    first = cls(id=ledger_id, time=time, asset=asset, amount=amount)
  elif kind == 'staking':
    first = Yield(id=ledger_id, time=time, asset=asset, amount=amount)
  elif kind == 'transfer':
    first = Transfer(id=ledger_id, time=time, asset=asset, amount=amount)
  elif kind == 'reward':
    first = Bonus(id=ledger_id, time=time, asset=asset, amount=amount)
  else:
    first = UnknownObservation(id=ledger_id, time=time, asset=asset, amount=amount)

  observations: list[LedgerObservation] = [first]
  fee = entry.get('fee')
  if fee:
    observations.append(
      FeeLeg(
        id=f'{ledger_id}-fee',
        time=time,
        asset=asset,
        amount=fee,
        event_type=first.type,
        event_id=ledger_id,
      )
    )
  return observations


@dataclass(frozen=True, kw_only=True)
class History(_History, Mixin):
  """Kraken implementation of `History`.

  One `HistoryRecord` per ledger row, keyed by the row's ledger id. Needs an API
  key with the `Data - Query ledger entries` permission.
  """

  async def history(
    self, start: datetime | None = None, end: datetime | None = None
  ) -> AsyncIterator[HistoryRecord]:
    """Stream the account ledger as one record per row, newest first.

    `start` is exclusive on the wire and in whole seconds, so it is sent one second
    early and the window is re-applied here to keep the SDK's inclusive bound.

    Args:
      start: Start of the window (inclusive). `None` reads from the account's
        first entry.
      end: End of the window (inclusive). `None` reads through now.
    """
    offset = 0
    while True:
      current = offset
      page = await self.call_kraken(
        lambda: self.client.spot.account.ledgers(
          start=int(start.timestamp()) - 1 if start is not None else None,
          end=int(end.timestamp()) if end is not None else None,
          ofs=current,
        )
      )
      rows = page.get('ledger') or {}
      for ledger_id, entry in rows.items():
        time = entry.get('time')
        if time is not None and start is not None and time < start:
          continue
        if time is not None and end is not None and time > end:
          continue
        yield HistoryRecord(
          observations=parse_entry(ledger_id, entry),
          provenance={'source': 'api', 'service': 'kraken', 'id': ledger_id},
        )
      offset += len(rows)
      if not rows or offset >= (page.get('count') or 0):
        return
