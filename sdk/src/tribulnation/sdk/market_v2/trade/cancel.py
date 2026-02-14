from typing_extensions import Sequence
from abc import abstractmethod
import asyncio

from tribulnation.sdk.core import SDK

class Cancel(SDK):
	@SDK.method
	@abstractmethod
	async def order(self, id: str):
		"""Cancel an order."""
		...
		
	@SDK.method
	async def orders(self, ids: Sequence[str]):
		"""Cancel multiple orders."""
		await asyncio.gather(*[self.order(id) for id in ids])
