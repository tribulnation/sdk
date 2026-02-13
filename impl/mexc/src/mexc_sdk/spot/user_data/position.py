from dataclasses import dataclass

from tribulnation.sdk.market.user_data.my_position import MyPosition as _MyPosition, Position

from mexc_sdk.core import MarketMixin
from .balances import Balances
from ..market_data import Info

@dataclass
class MyPosition(MarketMixin, _MyPosition):
  async def position(self) -> Position | None:
    info = await Info.info(self) # type: ignore
    balance = await Balances.balance(self, info.base) # type: ignore
    if balance.total > 0:
      return Position(size=balance.total)