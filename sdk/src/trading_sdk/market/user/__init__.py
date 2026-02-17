from dataclasses import dataclass as _dataclass

from trading_sdk.core import SDK
from .balances import Balances
from .position import Position, PerpPosition
from .trades import Trades
from .orders import Orders
from .funding import Funding

@_dataclass(frozen=True)
class UserData(SDK):
	Balances = Balances
	Position = Position
	Trades = Trades
	Orders = Orders
	balances: Balances
	position: Position
	trades: Trades
	orders: Orders
	
@_dataclass(frozen=True)
class PerpUserData(UserData):
	Position = PerpPosition
	Funding = Funding
	position: PerpPosition
	funding: Funding