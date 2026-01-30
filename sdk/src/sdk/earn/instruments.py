from typing_extensions import Literal, Sequence, Protocol
from dataclasses import dataclass
from decimal import Decimal
from datetime import timedelta

from sdk.core import SDK

InstrumentType = Literal['flexible', 'fixed']

@dataclass(kw_only=True)
class BaseInstrument:
	Type = InstrumentType
	type: Type
	asset: str
	apr: Decimal
	yield_asset: str
	min_qty: Decimal | None = None
	max_qty: Decimal | None = None
	url: str | None = None
	
@dataclass(kw_only=True)
class Flexible(BaseInstrument):
	type: Literal['flexible'] = 'flexible'
	
@dataclass(kw_only=True)
class Fixed(BaseInstrument):
	type: Literal['fixed'] = 'fixed'
	duration: timedelta

Instrument = Flexible | Fixed

class Instruments(SDK, Protocol):
  @SDK.method
  def instruments(
    self, *, types: Sequence[InstrumentType] | None = None,
    assets: Sequence[str] | None = None,
  ) -> Sequence[Instrument]:
    ...