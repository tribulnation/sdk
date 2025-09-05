from typing_extensions import TypedDict, Literal
from datetime import datetime

class Spot(TypedDict):
  type: Literal['spot']
  base: str
  quote: str

class Future(TypedDict):
  type: Literal['future']
  base: str
  quote: str
  expiration: datetime

class Perpetual(TypedDict):
  type: Literal['perp']
  base: str
  quote: str

class InversePerpetual(TypedDict):
  type: Literal['inverse_perp']
  currency: str

class BaseOption(TypedDict):
  strike: str
  expiration: datetime
  kind: Literal['call', 'put']

class Option(BaseOption):
  type: Literal['option']
  underlying: str
  settle: str

class InverseOption(BaseOption):
  type: Literal['inverse_option']
  underlying: str

class AnyInstrument(TypedDict):
  type: Literal['any']
  name: str

Instrument = Spot | Perpetual | InversePerpetual | Option | InverseOption | AnyInstrument