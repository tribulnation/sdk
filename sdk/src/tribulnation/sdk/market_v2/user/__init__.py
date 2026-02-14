from dataclasses import dataclass as _dataclass

from tribulnation.sdk.core import SDK
from .balances import Balances
from .position import Position, PerpPosition
from .trades import Trades
from .orders import Orders
from .funding import Funding

@_dataclass(frozen=True)
class UserData(SDK):
	balances: Balances
	position: Position
	trades: Trades
	orders: Orders
	
@_dataclass(frozen=True)
class PerpUserData(UserData):
	position: PerpPosition
	funding: Funding