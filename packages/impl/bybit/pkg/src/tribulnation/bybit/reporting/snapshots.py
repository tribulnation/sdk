"""A point-in-time view of the Bybit Unified Trading Account."""

from typing_extensions import Collection
from decimal import Decimal

from tribulnation.sdk.reporting import (
  ApiProvenance,
  Position,
  Snapshot,
  SnapshotRecord,
  SubaccountSnapshot,
)

from tribulnation.bybit.core import Mixin, num


async def snapshot(
  self: Mixin, assets: Collection[str] | None = None
) -> SnapshotRecord:
  """Fetch the account's current balances and open positions.

  Bybit's unified account is one pool -- no separate spot, margin or futures wallets
  to enumerate -- so this is a single `SubaccountSnapshot`.

  Args:
    assets: Keep balances for these coins only. `None` keeps every coin.
  """
  account = await self.unified_balance()
  balances: dict[str, Decimal] = {}
  for coin in account['coin'] if account is not None else []:
    if assets is not None and coin['coin'] not in assets:
      continue
    # `walletBalance` is `''` for a coin the account has never held; that is a
    # missing row rather than a zero balance, but either way it records as zero.
    balances[coin['coin']] = num(coin['walletBalance'])
  positions: dict[str, Position] = {}
  for p in await self.linear_positions():
    size = Decimal(p['size'])
    positions[p['symbol']] = Position(
      size=size if p['side'] == 'Buy' else -size,
      avg_price=num(p['avgPrice']),
    )
  return SnapshotRecord(
    snapshot=Snapshot(
      subaccounts=[SubaccountSnapshot(balances=balances, positions=positions)]
    ),
    provenance=ApiProvenance(
      id='bybit-uta-snapshot', source='api', service='typed_bybit'
    ),
  )
