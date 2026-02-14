from abc import abstractmethod
from decimal import Decimal

from tribulnation.sdk.core import SDK

class Index(SDK):
	@SDK.method
	@abstractmethod
	async def __call__(self) -> Decimal:
		"""Fetch the market's index price."""