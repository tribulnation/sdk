from dataclasses import dataclass
from decimal import Decimal

from trading_sdk.market.data import Index as _Index

from mexc_sdk.core import MarketMixin

@dataclass
class Index(MarketMixin, _Index):
  async def price(self) -> Decimal:
    raise NotImplementedError('MEXC futures index price is not implemented')
