from decimal import Decimal

from tribulnation.sdk.market import Position

from tribulnation.mexc.core.exc import wrap_exceptions
from .mixin import MarketMixin


@wrap_exceptions
async def position(self: MarketMixin) -> Position:
  r = await self.client.spot.account.info(recv_window=self.shared.recvWindow, validate=self.shared.validate)
  for b in r.get('balances', []):
    if b.get('asset') == self.info.get('baseAsset'):
      total = Decimal(b.get('free') or '0') + Decimal(b.get('locked') or '0')
      return Position(size=total)
  return Position()
