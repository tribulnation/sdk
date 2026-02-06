from typing_extensions import Any
from decimal import Decimal
from datetime import timezone, timedelta
import re
import pandas as pd
from tribulnation.sdk.reporting import FiatDeposit, FiatWithdrawal

from .. import util

end_time_regex = re.compile(r'End Time\(UTC\+(\d{2}):(\d{2})\)')

def parse_timezone(key: str) -> timezone:
  match = end_time_regex.match(key)
  assert match is not None
  hours, minutes = match.groups()
  return timezone(timedelta(hours=int(hours), minutes=int(minutes)))

# The Spot Statement doesn't include postings for fiat deposits and withdrawals, so we expect them to not match.
# @dataclass(kw_only=True)
# class FiatDeposit(BaseFiatDeposit, util.Operation):
#   tag: str = 'Spot From Fiat Account'
#   order_id: str

#   @property
#   def id(self) -> str:
#     return f'spot2fiat;{self.order_id}'

# @dataclass(kw_only=True)
# class FiatWithdrawal(BaseFiatWithdrawal, util.Operation):
#   tag: str = 'Spot To Fiat Account'
#   order_id: str
  
#   @property
#   def id(self) -> str:
#     return f'fiat2spot;{self.order_id}'

def parse_entry(row: pd.Series):
  cls = FiatDeposit if row['Trading Direction'] == 'Buy' else FiatWithdrawal
  order_id = str(row['Order ID'])
  prefix = 'spot2fiat' if row['Trading Direction'] == 'Buy' else 'fiat2spot'
  id = f'{prefix};{order_id}'
  return cls(
    id=id,
    asset=str(row['Trading Token']),
    qty=Decimal(str(row['Order Quantity'])),
    time=util.ensure_datetime(row['End Time']),
    fiat_currency=str(row['Settlement Token']),
    fiat_amount=Decimal(str(row['Order Amount'])),
    method=str(row['Payment Method']),
    details=dict(row),
  )

class fiat_otc_orders(util.Module):
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

  matching_mode = 'ge' # doesn't matter since we're not matching at all

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
  def load(path: str, *, skip_zero_changes: bool = True) -> pd.DataFrame:
    df = pd.read_excel(path, dtype={'Order Quantity': str, 'Order Amount': str})
    util.validate_schema(df, fiat_otc_orders.schema)
    key = util.find_key(df, end_time_regex)
    assert key is not None
    df['End Time'] = pd.to_datetime(df[key]).dt.tz_localize(parse_timezone(key)).dt.tz_convert(timezone.utc)
    if skip_zero_changes:
      df.drop(df[df['Order Quantity'].astype(float) == 0].index, inplace=True) # type: ignore
      df.drop(df[df['Order Amount'].astype(float) == 0].index, inplace=True) # type: ignore
      df.reset_index(drop=True, inplace=True)
    return df

  @staticmethod
  def parse(path: str, *_, skip_zero_changes: bool = True):
    """Parse fiat OTC orders log excel file.

    - `path`: Path to excel file
    """
    df = fiat_otc_orders.load(path, skip_zero_changes=skip_zero_changes)
    for posting in fiat_otc_orders.parse_df(df):
      yield posting

  @staticmethod
  def parse_df(df: pd.DataFrame):
    for _, row in df.iterrows():
      yield parse_entry(row)