from datetime import timedelta
from decimal import Decimal

from typed_hyperliquid.info.clearinghouse_state import ClearinghouseState
from tribulnation.sdk.market import PerpPosition

from tribulnation.hyperliquid.core import wrap_exceptions
from .mixin import PerpMarketMixin


def parse_position(state: ClearinghouseState, coin: str) -> PerpPosition:
  """The position on `coin` in one dex's `clearinghouseState`; flat when it lists none.

  Builder dexes name their coins with the dex prefix (`xyz:XYZ100`), as their asset
  metadata does. `liquidationPx` is the venue's estimate, `null` when it names none.
  """
  for entry in state['assetPositions']:
    pos = entry['position']
    if pos['coin'] == coin:
      px = pos['liquidationPx']
      liquidation = Decimal(px) if px is not None else None
      return PerpPosition(
        size=Decimal(pos['szi']),
        entry_price=Decimal(pos['entryPx']),
        liquidation_price=(
          liquidation if liquidation is not None and liquidation > 0 else None
        ),
      )
  return PerpPosition()


@wrap_exceptions
async def position(
  self: PerpMarketMixin, *, ttl: timedelta | None = None
) -> PerpPosition:
  """The position on this coin, from the dex's shared `clearinghouseState`."""
  state = await self.shared.clearinghouse_state(self.dex_name, ttl=ttl)
  return parse_position(state, self.asset_name)
