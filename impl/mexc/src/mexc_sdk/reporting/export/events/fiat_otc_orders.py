from typing_extensions import Any
from decimal import Decimal
from datetime import timezone, timedelta
import re
import pandas as pd

from trading_sdk.reporting.history import FiatDeposit, FiatWithdrawal
import trading_sdk.util.csv as util

end_time_regex = re.compile(r'End Time\(UTC\+(\d{2}):(\d{2})\)')

def parse_timezone(key: str) -> timezone:
  match = end_time_regex.match(key)
  assert match is not None
  hours, minutes = match.groups()
  return timezone(timedelta(hours=int(hours), minutes=int(minutes)))

def parse_entry(row: pd.Series):
  cls = FiatDeposit if row['Trading Direction'] == 'Buy' else FiatWithdrawal
  order_id = str(row['Order ID'])
  return cls(
    id=order_id,
    asset=str(row['Trading Token']),
    qty=Decimal(str(row['Order Quantity'])),
    time=util.ensure_datetime(row['End Time']),
    fiat_currency=str(row['Settlement Token']),
    fiat_amount=Decimal(str(row['Order Amount'])),
    method=str(row['Payment Method']),
    raw=row.to_dict(),
    source='export:fiat_otc_orders',
  )

class fiat_otc_orders:
  """Parsing MEXC's fiat OTC orders.

  *This data is already included in the spot statement.*

    It must be downloaded as an Excel file from:
    
    > [Data Export](https://www.mexc.com/support/data-export) > `Fiat` > `OTC Orders` > `Excel`

    **Expected schema:**

    - `Status`
    - `Order ID`
    - `End Time(<timezone>)`, e.g. `End Time(UTC+03:00)`
    - `Trading Token`
    - `Trading Direction :: Buy | Sell`
    - `Order Quantity`
    - `Settlement Token`	
    - `Order Amount`
    - `Payment Method`
    """

  schema: util.Schema = {
    'Status': str,
    'Order ID': Any, # type: ignore
    end_time_regex: str,
    'Trading Token': str,
    'Trading Direction': re.compile(r'^(Buy|Sell)$'),
    'Order Quantity': str,
    'Settlement Token': str,
    'Order Amount': str,
  }

  @staticmethod
  def load(path: str) -> pd.DataFrame:
    df = pd.read_excel(path, dtype={'Order Quantity': str, 'Order Amount': str})
    util.validate_schema(df, fiat_otc_orders.schema)
    key = util.find_key(df, end_time_regex)
    assert key is not None
    df['End Time'] = pd.to_datetime(df[key]).dt.tz_localize(parse_timezone(key)).dt.tz_convert(timezone.utc)
    return df

  @staticmethod
  def parse(path: str, *_, **__):
    """Parse fiat OTC orders log excel file.

    - `path`: Path to excel file
    """
    df = fiat_otc_orders.load(path)
    yield from fiat_otc_orders.parse_df(df)

  @staticmethod
  def parse_df(df: pd.DataFrame):
    for _, row in df.iterrows():
      yield parse_entry(row)