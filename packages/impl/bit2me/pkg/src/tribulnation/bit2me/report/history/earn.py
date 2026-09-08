"""Earn reward payouts, from `v1/earn/wallets/{walletId}/movements`.

There is no cross-wallet movements endpoint, so the walk is per Earn wallet:
`v2/earn/wallets` enumerates them, then each one's movements are paged
`createdAt`-descending and filtered to `type == 'reward'`.
"""

from typing_extensions import Sequence
from dataclasses import dataclass
from datetime import datetime
import asyncio

from tribulnation.sdk.core import SDK
from tribulnation.sdk.reporting import Yield
from tribulnation.bit2me.core import Mixin

from typed_bit2me.schemas import EarnWalletListEntry
from typed_bit2me.v1.earn.wallets.list_movements import DataItem

WALLETS_PAGE = 100
"""Earn wallets fetched per page."""
MOVEMENTS_PAGE = 50
"""Movements fetched per page, per Earn wallet."""


def parse_reward(movement: DataItem) -> Yield | None:
  """Map one Earn reward movement onto a `Yield`, or skip a non-reward."""
  time = movement.get('createdAt')
  if movement.get('type') != 'reward' or time is None:
    return None
  # `netAmount` is the payout after any withholding; `amount` is the gross, and is
  # what a movement without withholding reports.
  net = movement.get('netAmount') or movement.get('amount') or {}
  value = net.get('value')
  currency = net.get('currency')
  if value is None or currency is None:
    return None
  return Yield(
    id=movement.get('movementId'),
    time=time,
    asset=currency,
    amount=value,
  )


@dataclass(frozen=True, kw_only=True)
class EarnYields(Mixin):
  """The account's Earn reward payouts."""

  @SDK.method
  async def earn_wallets(self) -> Sequence[EarnWalletListEntry]:
    """Enumerate the account's Earn wallets."""
    out: list[EarnWalletListEntry] = []
    offset = 0
    while True:
      current = offset
      page = await self.call_bit2me(
        lambda: self.client.v2.earn.wallets(offset=current, limit=WALLETS_PAGE)
      )
      entries = page.get('data', [])
      out.extend(entries)
      offset += len(entries)
      if not entries or offset >= (page.get('total') or 0):
        return out

  @SDK.method
  async def wallet_yields(
    self, wallet_id: str, start: datetime, end: datetime
  ) -> Sequence[Yield]:
    """Fetch one Earn wallet's reward payouts in a window.

    Movements are requested newest-first, so the walk stops at the first movement
    older than `start`.

    Args:
      wallet_id: Earn wallet to read.
      start: Start of the window (inclusive).
      end: End of the window (inclusive).
    """
    out: list[Yield] = []
    offset = 0
    while True:
      current = offset
      page = await self.call_bit2me(
        lambda: self.client.v1.earn.wallets.list_movements(
          wallet_id=wallet_id,
          offset=current,
          limit=MOVEMENTS_PAGE,
          sort_by='createdAt',
          sort_direction='descending',
        )
      )
      for movement in page['data']:
        time = movement.get('createdAt')
        if time is not None and time < start:
          return out
        if time is not None and time > end:
          continue
        if (reward := parse_reward(movement)) is not None:
          out.append(reward)
      offset += len(page['data'])
      if not page['data'] or offset >= page['total']:
        return out

  @SDK.method
  async def earn_yields(self, start: datetime, end: datetime) -> Sequence[Yield]:
    """Fetch every Earn reward payout across the account's wallets in a window."""
    wallets = await self.earn_wallets()
    groups = await asyncio.gather(
      *[self.wallet_yields(wallet['walletId'], start, end) for wallet in wallets]
    )
    return [reward for group in groups for reward in group]
