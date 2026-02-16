from typing_extensions import Literal, Collection, Sequence, ClassVar
from abc import abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from datetime import timedelta

from trading_sdk.core import SDK

InstrumentTag = Literal['flexible', 'fixed', 'one-time', 'new-users', 'staking']

@dataclass(kw_only=True)
class Instrument:
	Tag: ClassVar = InstrumentTag
	tags: Sequence[InstrumentTag]
	asset: str
	apr: Decimal
	"""Annual Percent Rate, as a fraction of 1 (0.01 = 1%)"""
	yield_asset: str | None = None
	"""Asset that yields the interest. If not provided, it's the same as the subscribed asset."""
	min_qty: Decimal | None = None
	"""Minimum quantity of the asset to invest"""
	max_qty: Decimal | None = None
	"""Maximum quantity of the asset to invest"""
	url: str | None = None
	duration: timedelta | None = None
	"""Duration of the instrument"""
	id: str | None = None
	"""Unique identifier for the instrument, if available."""

class Instruments(SDK):
  @SDK.method
  @abstractmethod
  async def instruments(
    self, *, tags: Collection[InstrumentTag] | None = None,
    assets: Collection[str] | None = None,
  ) -> Sequence[Instrument]:
    """Fetch instruments from the exchange.

    - `tags`: Filter by tags. Returns all assets matching at least one of the tags.
    - `assets`: Filter by (subscription) assets.
    """