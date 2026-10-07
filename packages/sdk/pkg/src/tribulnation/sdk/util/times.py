"""Wire timestamp normalization shared by venue implementations."""

from datetime import datetime

from typed_core.times import EpochConverter


def epoch_time(
  value: datetime | int | float | str, converter: EpochConverter
) -> datetime:
  """Normalize an epoch timestamp field to a datetime.

  Validated typed clients already decode such fields to datetimes; unvalidated ones
  pass the raw wire number (or numeral string) through.

  Args:
    value: The field as the typed client returned it.
    converter: The venue's converter for the field's epoch unit.
  """
  return value if isinstance(value, datetime) else converter.parse(value)
