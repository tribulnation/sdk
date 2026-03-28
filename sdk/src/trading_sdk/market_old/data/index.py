from abc import abstractmethod
from decimal import Decimal

from trading_sdk.core import SDK

class Index(SDK):
	@SDK.method
	@abstractmethod
	async def price(self) -> Decimal:
		"""Fetch the market's index price."""

	@SDK.method
	async def __call__(self) -> Decimal:
		"""Fetch the market's index price."""
		return await self.price()