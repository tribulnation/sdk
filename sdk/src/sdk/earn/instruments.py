from typing_extensions import Literal, Sequence, Protocol
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime

from sdk.core import SDK

@dataclass
class BaseInstrument:
	Type = Literal['flexible', 'fixed']
	asset: str
	apr: Decimal
	yield_asset: str
	min_qty: Decimal | None = None
	max_qty: Decimal | None = None
	url: str | None = None
	
@dataclass
class Flexible(BaseInstrument):
	type: Literal['flexible'] = 'flexible'
	
@dataclass
class Fixed(BaseInstrument):
	type: Literal['fixed'] = 'fixed'
	period: datetime

Instrument = Flexible | Fixed

class Instruments(SDK, Protocol):
  @SDK.method
  def instruments(
    self, *, types: Sequence[Instrument.Type] | None = None,
    assets: Sequence[str] | None = None,
  ) -> Sequence[Instrument]:
    ...