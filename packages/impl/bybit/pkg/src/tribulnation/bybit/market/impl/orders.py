"""Reading this market's resting orders."""

from tribulnation.sdk.market import OrderState

from .mixin import MarketMixin
from .parse import parse_order


async def open_orders(self: MarketMixin) -> list[OrderState]:
  """Fetch every resting order on this market, one cursor page at a time."""
  out: list[OrderState] = []
  cursor: str | None = None
  while True:
    page = await self.call_bybit(
      lambda: self.client.trade.open_orders(
        self.category, symbol=self.symbol, cursor=cursor, validate=self.validate
      )
    )
    out.extend(parse_order(o) for o in page['list'])
    cursor = page.get('nextPageCursor')
    if not cursor:
      break
  return out
