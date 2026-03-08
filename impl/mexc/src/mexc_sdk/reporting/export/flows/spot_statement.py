from decimal import Decimal
from datetime import timedelta, timezone
import re
import pandas as pd

from trading_sdk.reporting.history import Flow
import trading_sdk.util.csv as util

creation_time_regex = re.compile(r'Creation Time\(UTC\+(\d{2}):(\d{2})\)')

def parse_timezone(key: str) -> timezone:
  match = creation_time_regex.match(key)
  if match is None:
    raise util.InvalidSchema([util.MissingColumn(creation_time_regex, str)])
  hours, minutes = match.groups()
  return timezone(timedelta(hours=int(hours), minutes=int(minutes)))

class spot_statement:
  """Parsing MEXC's spot statement.

  Data must be downloaded as an Excel file from:
  
  > [Data Export](https://www.mexc.com/support/data-export) > `Spot` > `Spot Statement` > `Excel`

  **Expected schema:**

  - `Creation Time(<timezone>)`, e.g. `Creation Time(UTC+03:00)`
  - `Crypto`
  - `Transaction Type`
  - `Quantity`
  """

  @staticmethod
  def parse_posting(row: pd.Series) -> Flow:
    return Flow(
      asset=str(row['Crypto']),
      change=Decimal(str(row['Quantity'])),
      time=util.ensure_datetime(str(row['Creation Time'])).replace(tzinfo=timezone.utc),
      event_tag=str(row['Transaction Type']),
      raw=row.to_dict(),
      source='export:spot_statement',
    )

  schema: util.Schema = {
    creation_time_regex: str,
    'Crypto': str,
    'Transaction Type': str,
    'Quantity': str,
  }

  @staticmethod
  def load(path: str) -> pd.DataFrame:
    df = pd.read_excel(path, dtype={'Quantity': str})
    util.validate_schema(df, spot_statement.schema)
    key = util.find_key(df, creation_time_regex)
    assert key is not None
    df['Creation Time'] = pd.to_datetime(df[key]).dt.tz_localize(parse_timezone(key)).dt.tz_convert(timezone.utc)
    return df

  @staticmethod
  def parse(path: str, *_, **__):
    df = spot_statement.load(path)
    yield from spot_statement.parse_df(df)

  @staticmethod
  def parse_df(df: pd.DataFrame):
    for _, row in df.iterrows():
      yield spot_statement.parse_posting(row)
