from typing_extensions import Callable
from decimal import Decimal
from datetime import datetime, timezone
from collections import Counter
import re
import pandas as pd
from trading_sdk.reporting.transactions import Trade, Fee

from .. import util

fee_regex = re.compile(r'([-\d\.]+)([A-Z0-9]+)$')

# @dataclass
# class SpotTrade(Trade, util.Operation):
#   time_idx: int = 0
#   """Index of the transaction within the same instant."""

#   @property
#   def expected_postings(self) -> list[util.TaggedPosting]:
#     s = 1 if self.side == 'BUY' else -1
#     postings = [
#       util.TaggedPosting(
#         time=self.time,
#         tag='Spot Spot Trading',
#         posting=CurrencyPosting(
#           asset=self.base,
#           change=s * self.qty,
#         )
#       ),
#       util.TaggedPosting(
#         time=self.time,
#         tag='Spot Spot Trading',
#         posting=CurrencyPosting(
#           asset=self.quote,
#           change=-s * self.qty * self.price,
#         )
#       ),
#     ]
#     if self.fee is not None:
#       postings.append(util.TaggedPosting(
#         time=self.time,
#         tag='Spot Spot Trading Fees',
#         posting=CurrencyPosting(
#           asset=self.fee.asset,
#           change=-self.fee.amount,
#         )
#       ))
#     return postings

  # @property
  # def id(self) -> str:
  #   id = f'{self.base}_{self.quote};{self.time:%Y-%m-%d %H:%M:%S}'
  #   if self.time_idx:
  #     id += f';{self.time_idx}'
  #   return id
  

def parse_entry(row: pd.Series, time_idx: Callable[[datetime], int]):
  base = str(row['base'])
  quote = str(row['quote'])
  time = util.ensure_datetime(row['Time(UTC)'])
  id = f'{base}_{quote};{time:%Y-%m-%d %H:%M:%S}'
  if (idx := time_idx(time)) > 0:
    id += f';{idx}'
  fee_amount = Decimal(str(row['fee_amount']))
  if fee_amount == 0:
    fee = None
  else:
    fee = Fee(fee_amount, str(row['fee_asset']))
  return Trade(
    id=id, time=time, base=base, quote=quote,
    qty=Decimal(str(row['Executed Amount'])),
    price=Decimal(str(row['Filled Price'])),
    liquidity='taker' if row['Role'] == 'Taker' else 'maker',
    side='buy' if row['Side'] == 'Buy' else 'sell',
    fee=fee,
    details=dict(row),
  )

class spot_trades(util.Module):
  """Parsing MEXC's spot trades log.

  *This data is already included in the spot statement.*

    It must be downloaded as an Excel file from:
    
    > [Data Export](https://www.mexc.com/support/data-export) > `Spot` > `Spot Trade History` > `Excel`

    **Expected schema:**

    - `Pairs :: <base>_<quote>`
    - `Time`
    - `Side :: Buy | Sell`
    - `Filled Price`
    - `Executed Amount :: Quantity`
    - `Fee :: <amount><asset>`
    - `Role :: Taker | Maker`
    """

  matching_mode = 'eq'

  schema: util.Schema = {
    'Pairs': re.compile(r"^.+_.+$"),
    'Time': str,
    'Side': re.compile(r"^(Buy|Sell)$"),
    'Filled Price': str,
    'Executed Amount': str,
    'Fee': fee_regex,
    'Role': re.compile(r"^(Taker|Maker)$"),
  }

  @staticmethod
  def load(path: str, tz: timezone, *, skip_zero_changes: bool = True) -> pd.DataFrame:
    df = pd.read_excel(path, dtype={'Filled Price': str, 'Executed Amount': str})
    util.validate_schema(df, spot_trades.schema)
    if skip_zero_changes:
      df.drop(df[df['Executed Amount'].astype(float) == 0].index, inplace=True) # type: ignore
      df.reset_index(drop=True, inplace=True)
    df[['base', 'quote']] = df['Pairs'].str.split('_', expand=True)
    df[['fee_amount', 'fee_asset']] = df['Fee'].str.extract(fee_regex)
    df['Time(UTC)'] = pd.to_datetime(df['Time']).dt.tz_localize(tz).dt.tz_convert(timezone.utc)
    return df

  @staticmethod
  def parse(path: str, tz: timezone, *, skip_zero_changes: bool = True):
    """Parse spot trades history excel file.

    - `path`: Path to excel file
    - `tz`: Timezone of the times in the log
    """
    df = spot_trades.load(path, tz, skip_zero_changes=skip_zero_changes)
    for posting in spot_trades.parse_df(df):
      yield posting

  @staticmethod
  def parse_df(df: pd.DataFrame):
    times = Counter[datetime]()
    for _, row in df.iterrows():
      entry = parse_entry(row, time_idx=times.__getitem__)
      times[entry.time] += 1
      yield entry