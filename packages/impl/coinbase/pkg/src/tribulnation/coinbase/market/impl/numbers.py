"""Numeric reads for the product catalogue.

The venue blanks out a product's activity fields (`price`, `volume_24h`,
`best_bid_price`, ...) with `''` when it has no value for them, which the client declares
as `Decimal | Literal['']`. This is where that sentinel becomes `None`.
"""

from typing_extensions import Literal
from decimal import Decimal

BLANK = ''


def parse_optional_decimal(value: 'Decimal | Literal[""] | None') -> Decimal | None:
  """Read a catalogue field the venue blanks out when it has no value."""
  if value is None or value == BLANK:
    return None
  return value
