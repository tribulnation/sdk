"""Reading this market's resting orders, in either account mode."""

from tribulnation.sdk.market import OrderState

from .mixin import MarketMixin
from .parse import parse_mix_order, parse_spot_order, parse_uta_order
from .util import PAGE


async def open_orders(self: MarketMixin) -> list[OrderState]:
  """Fetch every resting order on this market, one page at a time.

  Every page is its own `call`, so a throttled page retries alone.
  """
  self.require_account_surface()
  out: list[OrderState] = []
  if await self.is_uta():
    paging = self.client.uta.trade.order.unfilled_paged(
      self.product, symbol=self.symbol, limit=PAGE, validate=self.validate
    )
    async for rows in paging.via(self.call):
      out.extend(parse_uta_order(o) for o in rows)
  elif self.product == 'SPOT':
    # The spot listing has no paged variant: it pages by `idLessThan`, the last row's
    # order id, and a page shorter than the limit is the last one.
    cursor: str | None = None
    while True:
      rows = await self.call(
        lambda: self.client.classic.spot.order.open(
          symbol=self.symbol, limit=PAGE, id_less_than=cursor, validate=self.validate
        )
      )
      out.extend(parse_spot_order(o) for o in rows)
      if len(rows) < PAGE:
        break
      cursor = rows[-1]['orderId']
  else:
    paging = self.client.classic.mix.order.open_paged(
      symbol=self.symbol, product_type=self.product, limit=PAGE, validate=self.validate
    )
    async for rows in paging.via(self.call):
      out.extend(parse_mix_order(o) for o in rows)
  return out
