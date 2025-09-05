from typing_extensions import Protocol
from .funding_rate_history import FundingRateHistory
from .my_trades import MyTrades

class UserData(FundingRateHistory, MyTrades, Protocol):
  ...