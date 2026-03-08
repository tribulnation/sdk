from decimal import Decimal
from datetime import timedelta, timezone
import re
import pandas as pd

from trading_sdk.reporting import Flow
import trading_sdk.util.csv as util

time_regex = re.compile(r'Time\(UTC\+(\d{2}):(\d{2})\)')

def parse_timezone(key: str) -> timezone:
  match = time_regex.match(key)
  assert match is not None
  hours, minutes = match.groups()
  return timezone(timedelta(hours=int(hours), minutes=int(minutes)))

class futures_capital_flow:
  """Parsing MEXC's futures capital flow.

  Data must be downloaded as an Excel file from:
  
  > [Data Export](https://www.mexc.com/support/data-export) > `Futures` > `Futures Capital Flow` > `Excel`

  **Expected schema:**
  - `Creation Time(<timezone>)`, e.g. `Creation Time(UTC+03:00)`
  - `Crypto`
  - `Fund Type`
  - `Amount`
  """  

  @staticmethod
  def parse_posting(row: pd.Series) -> Flow:
    return Flow(
      asset=str(row['Crypto']),
      change=Decimal(str(row['Amount'])),
      time=util.ensure_datetime(str(row['Creation Time'])).replace(tzinfo=timezone.utc),
      event_tag=str(row['Fund Type']),
      raw=row.to_dict(),
      source='export:futures_capital_flow',
    )

  schema: util.Schema = {
    time_regex: str,
    'Crypto': str,
    'Fund Type': str,
    'Amount': str,
  }

  @staticmethod
  def load(path: str) -> pd.DataFrame:
    df = pd.read_excel(path, dtype={'Amount': str})
    util.validate_schema(df, futures_capital_flow.schema)
    key = util.find_key(df, time_regex)
    assert key is not None
    df['Creation Time'] = pd.to_datetime(df[key]).dt.tz_localize(parse_timezone(key)).dt.tz_convert(timezone.utc)
    df.reset_index(drop=True, inplace=True)
    return df

  @staticmethod
  def parse(path: str, *_, **__):
    df = futures_capital_flow.load(path)
    yield from futures_capital_flow.parse_df(df)

  @staticmethod
  def parse_df(df: pd.DataFrame):
    for _, row in df.iterrows():
      yield futures_capital_flow.parse_posting(row)