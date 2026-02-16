from dataclasses import dataclass as _dataclass

from trading_sdk.core import SDK
from .place import Place
from .cancel import Cancel

@_dataclass(frozen=True)
class Trading(SDK):
	place: Place
	cancel: Cancel