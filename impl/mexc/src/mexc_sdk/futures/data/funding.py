from dataclasses import dataclass
from datetime import datetime
from typing_extensions import AsyncIterable, Sequence

from trading_sdk.market.data import Funding as _Funding

from mexc_sdk.core import MarketMixin

@dataclass
class Funding(MarketMixin, _Funding):
  def history(self, start: datetime, end: datetime) -> AsyncIterable[Sequence[_Funding.Funding]]:
    raise NotImplementedError('MEXC futures funding history is not implemented')

  async def next(self) -> _Funding.Funding:
    raise NotImplementedError('MEXC futures next funding rate is not implemented')
