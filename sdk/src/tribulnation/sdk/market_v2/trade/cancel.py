from typing_extensions import Sequence, Any
from abc import abstractmethod
from dataclasses import dataclass
import asyncio

from tribulnation.sdk.core import SDK

class Cancel(SDK):

	@dataclass(kw_only=True)
	class Result:
		details: Any = None

	@SDK.method
	@abstractmethod
	async def order(self, id: str) -> Result:
		"""Cancel an order."""
		
	@SDK.method
	async def orders(self, ids: Sequence[str]) -> Sequence[Result]:
		"""Cancel multiple orders."""
		return await asyncio.gather(*[self.order(id) for id in ids])
