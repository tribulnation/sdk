"""On-chain deposits and withdrawals, from `v3/wallet/transaction`.

`v3` rather than the `v2` the PoC mapped: identical rows, but cursor-paginated in
strict `createdAt`-descending order, so a window walk stops at the first row older
than `start` instead of sweeping a whole year. (`v1` is deprecated in `typed_bit2me`
and gone upstream -- it answers `404 Cannot GET /v1/wallet/transaction`.)

The operation filter is `receive`/`send`, not `deposit`/`withdrawal`: those select
the fiat bank and card rows instead, which is why asking for `deposit` and then
keeping only blockchain counterparties yields nothing.
"""

from typing_extensions import Literal, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from tribulnation.sdk.core import SDK
from tribulnation.sdk.reporting import CryptoDeposit, CryptoWithdrawal, Fee
from tribulnation.bit2me.core import Mixin

from typed_bit2me.v3.wallet.transactions import WalletTransaction

TRANSACTIONS_PAGE = 100
"""Rows per page."""


def parse_fee(row: WalletTransaction) -> Fee | None:
  """Read a transaction's network fee, when it reports one."""
  network = (row.get('fee') or {}).get('network')
  if network is None:
    return None
  amount = network.get('amount')
  asset = network.get('currency')
  if amount is None or asset is None:
    return None
  return Fee(amount=amount, asset=asset)


def parse_deposit(row: WalletTransaction) -> CryptoDeposit | None:
  """Map one completed on-chain credit onto a `CryptoDeposit`, or skip it."""
  origin = row.get('origin') or {}
  destination = row.get('destination') or {}
  time = row.get('date')
  asset = destination.get('currency')
  if origin.get('class') != 'blockchain' or time is None or asset is None:
    return None
  if row.get('status') != 'completed':
    return None
  return CryptoDeposit(
    id=row.get('id'),
    time=time,
    asset=asset,
    amount=destination.get('amount', Decimal(0)),
    # On a deposit the blockchain side is the origin, but it carries neither
    # `address` nor `addressNetwork` -- both sit on the crediting pocket instead,
    # so the network is read off the destination and the sender is never reported.
    network=destination.get('addressNetwork'),
    tx_id=(row.get('transaction') or {}).get('hash'),
    src_address=origin.get('address'),
    dst_address=destination.get('address'),
    fee=parse_fee(row),
  )


def parse_withdrawal(row: WalletTransaction) -> CryptoWithdrawal | None:
  """Map one completed on-chain debit onto a `CryptoWithdrawal`, or skip it."""
  origin = row.get('origin') or {}
  destination = row.get('destination') or {}
  time = row.get('date')
  asset = origin.get('currency')
  if destination.get('class') != 'blockchain' or time is None or asset is None:
    return None
  # Cancelled withdrawals stay in the listing carrying the amount they would have sent.
  if row.get('status') != 'completed':
    return None
  return CryptoWithdrawal(
    id=row.get('id'),
    time=time,
    asset=asset,
    amount=-origin.get('amount', Decimal(0)),
    network=destination.get('addressNetwork'),
    tx_id=(row.get('transaction') or {}).get('hash'),
    src_address=origin.get('address'),
    dst_address=destination.get('address'),
    fee=parse_fee(row),
  )


@dataclass(frozen=True, kw_only=True)
class CryptoTransfers(Mixin):
  """The account's on-chain deposits and withdrawals.

  Three fields the source cannot fill, confirmed across every `receive`/`send` row
  this endpoint returns: `tx_id` (the `transaction` object only ever carries
  `confirmedAt`/`confirmationCount`, never the `hash` its schema declares),
  `src_address` (only the pocket side of a transfer carries an address, in both
  directions) and `fee` (no row carries a `fee` object at all -- the proforma used
  by `withdrawal_methods` is the only place a withdrawal fee shows up).
  """

  @SDK.method
  async def wallet_transactions(
    self,
    start: datetime,
    end: datetime,
    *,
    operation: Literal['receive', 'send'],
  ) -> Sequence[WalletTransaction]:
    """Fetch the wallet transactions of one operation within a window.

    Pages are strictly `createdAt`-descending -- that ordering is the cursor's own
    definition, not an incidental sort -- so the walk stops at the first row older
    than `start` rather than reading the account's whole history.

    Args:
      start: Start of the window (inclusive).
      end: End of the window (inclusive).
      operation: `receive` for on-chain credits, `send` for on-chain debits.
    """
    out: list[WalletTransaction] = []
    cursor: str | None = None
    while True:
      current = cursor
      page = await self.call_bit2me(
        lambda: self.client.v3.wallet.transactions(
          operation=operation, limit=TRANSACTIONS_PAGE, cursor=current
        )
      )
      for row in page['data']:
        time = row.get('date')
        if time is not None and time < start:
          return out
        if time is None or time <= end:
          out.append(row)
      info = page['pageInfo']
      cursor = info['endCursor']
      if not info['hasNextPage'] or cursor is None:
        return out

  @SDK.method
  async def crypto_deposits(
    self, start: datetime, end: datetime
  ) -> Sequence[CryptoDeposit]:
    """Fetch the account's completed on-chain deposits in a window."""
    rows = await self.wallet_transactions(start, end, operation='receive')
    return [parsed for row in rows if (parsed := parse_deposit(row)) is not None]

  @SDK.method
  async def crypto_withdrawals(
    self, start: datetime, end: datetime
  ) -> Sequence[CryptoWithdrawal]:
    """Fetch the account's completed on-chain withdrawals in a window."""
    rows = await self.wallet_transactions(start, end, operation='send')
    return [parsed for row in rows if (parsed := parse_withdrawal(row)) is not None]
