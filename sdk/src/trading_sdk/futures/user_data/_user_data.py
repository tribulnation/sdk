from typing_extensions import Protocol

from trading_sdk.market import UserData as _UserData
from .my_funding_history import MyFundingHistory

class UserData(_UserData, MyFundingHistory, Protocol):
  ...