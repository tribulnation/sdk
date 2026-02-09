from typing_extensions import AsyncIterable
from dataclasses import dataclass

from tribulnation.sdk.market.market_streams.trades import Trades as _Trades, Trade
from mexc_sdk.core import MarketMixin, wrap_exceptions

@dataclass
class Trades(MarketMixin, _Trades):
  @wrap_exceptions
  async def trades_stream(self) -> AsyncIterable[Trade]:
    raise NotImplementedError
    yield
