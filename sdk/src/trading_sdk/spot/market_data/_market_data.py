from typing_extensions import Protocol
from .depth import Depth
from .exchange_info import ExchangeInfo
from .time import Time
from .agg_trades import AggTrades
from .candles import Candles

class MarketData(Depth, ExchangeInfo, Time, AggTrades, Candles, Protocol):
  ...