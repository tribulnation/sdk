from decimal import Decimal
from datetime import timedelta, timezone
import re
import pandas as pd

from trading_sdk.reporting.history import Yield
import trading_sdk.util.csv as util

creation_time_regex = re.compile(r'Creation Time\(UTC\+(\d{2}):(\d{2})\)')

def parse_timezone(key: str) -> timedelta:
  match = creation_time_regex.match(key)
  if match is None:
    raise util.InvalidSchema([util.MissingColumn(creation_time_regex, str)])
  hours, minutes = match.groups()
  return timedelta(hours=int(hours), minutes=int(minutes))

def parse_entry(row: pd.Series):
  asset = str(row['Crypto'])
  time = util.ensure_datetime(str(row['Creation Time'])).replace(tzinfo=timezone.utc)
  return Yield(
    asset=asset,
    time=time,
    qty=Decimal(str(row['Quantity'])),
    raw=row.to_dict(),
    source='export:fixed_earn',
  )

class fixed_earn:
  """Parsing MEXC's fixed earn log.

  *This data is already included in the spot statement.*

    It must be downloaded as an Excel file from:
    
    > [Data Export](https://www.mexc.com/support/data-export) > `Earn` > `Fixed` > `Excel`

    **Expected schema:**

    - `Creation Time(<timezone>)`, e.g. `Creation Time(UTC+03:00)`
    - `Crypto`
    - `Transaction Type`
    - `Quantity`
    """

  schema: util.Schema = {
    creation_time_regex: str,
    'Crypto': str,
    'Transaction Type': str,
    'Quantity': str,
  }

  @staticmethod
  def load(path: str) -> pd.DataFrame:
    df = pd.read_excel(path, dtype={'Quantity': str})
    util.validate_schema(df, fixed_earn.schema)
    if len(df) == 0:
      return df
    key = util.find_key(df, creation_time_regex)
    assert key is not None
    df['Creation Time'] = pd.to_datetime(df[key]) - parse_timezone(key)
    return df

  @staticmethod
  def parse(path: str, *_, **__):
    df = fixed_earn.load(path)
    yield from fixed_earn.parse_df(df)

  @staticmethod
  def parse_df(df: pd.DataFrame):
    for _, row in df.iterrows():
      yield parse_entry(row)
