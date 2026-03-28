from dataclasses import dataclass as _dataclass
from trading_sdk.core import SDK

from .rules import Rules
from .depth import Depth
from .funding import Funding
from .index import Index

@_dataclass(frozen=True)
class MarketData(SDK):
	Rules = Rules
	Depth = Depth
	rules: Rules
	depth: Depth

@_dataclass(frozen=True)
class PerpMarketData(MarketData):
	Funding = Funding
	Index = Index
	funding: Funding
	index: Index