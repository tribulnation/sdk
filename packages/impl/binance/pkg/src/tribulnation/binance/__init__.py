from dataclasses import dataclass as _dataclass, field as _field

from .core import SdkMixin
from .earn import Earn
from .wallet import Wallet


@_dataclass
class Binance(SdkMixin):
	earn: Earn = _field(init=False)
	wallet: Wallet = _field(init=False)

	def __post_init__(self):
		self.earn = Earn(self.client, validate=self.validate)
		self.wallet = Wallet(self.client, validate=self.validate)
