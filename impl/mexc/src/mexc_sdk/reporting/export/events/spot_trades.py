from decimal import Decimal
from datetime import timezone
import re
import pandas as pd

from trading_sdk.reporting.history import SpotTrade
import trading_sdk.util.csv as util

fee_regex = re.compile(r'([-\d\.]+)([A-Z0-9]+)$')


def parse_entry(row: pd.Series):
  return SpotTrade(
    time=util.ensure_datetime(row['Time(UTC)']),
    base=str(row['base']),
    quote=str(row['quote']),
    qty=Decimal(str(row['Executed Amount'])),
    price=Decimal(str(row['Filled Price'])),
    liquidity='taker' if row['Role'] == 'Taker' else 'maker',
    side='buy' if row['Side'] == 'Buy' else 'sell',
    fee=Decimal(str(row['fee_amount'])),
    fee_asset=str(row['fee_asset']),
    raw=row.to_dict(),
    source='export:spot_trades',
  )

class spot_trades:
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
  def load(path: str, tz: timezone) -> pd.DataFrame:
    df = pd.read_excel(path, dtype={'Filled Price': str, 'Executed Amount': str})
    util.validate_schema(df, spot_trades.schema)
    df[['base', 'quote']] = df['Pairs'].str.split('_', expand=True)
    df[['fee_amount', 'fee_asset']] = df['Fee'].str.extract(fee_regex)
    df['Time(UTC)'] = pd.to_datetime(df['Time']).dt.tz_localize(tz).dt.tz_convert(timezone.utc)
    return df

  @staticmethod
  def parse(path: str, tz: timezone, *_, **__):
    """Parse spot trades history excel file.

    - `path`: Path to excel file
    - `tz`: Timezone of the times in the log
    """
    df = spot_trades.load(path, tz)
    yield from spot_trades.parse_df(df)

  @staticmethod
  def parse_df(df: pd.DataFrame):
    for _, row in df.iterrows():
      yield parse_entry(row)