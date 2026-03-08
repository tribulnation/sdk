from decimal import Decimal
from datetime import timezone
import re
import pandas as pd

from trading_sdk.reporting.history import SpotTrade
import trading_sdk.util.csv as util

class spot_order_details:
  """Parsing Bitget's spot order details export.

  Data must be downloaded as a CSV file from:

  > Bitget > Data Export > Spot > Spot Order Details

  **Expected schema:**

  - `Date`
  - `Trading pair`
  - `Base Asset`
  - `Quote Asset`
  - `Direction`
  - `Price`
  - `Amount`
  - `Total`
  - `Fee`
  - `Fee Coin`
  """

  pair_regex = re.compile(r'^[A-Z0-9]+/[A-Z0-9]+$')
  asset_regex = re.compile(r'^[A-Z0-9]+$')
  direction_regex = re.compile(r'^(buy|sell)$', re.IGNORECASE)

  schema: util.Schema = {
    'Date': str,
    'Trading pair': pair_regex,
    'Base Asset': asset_regex,
    'Quote Asset': asset_regex,
    'Direction': direction_regex,
    'Price': str,
    'Amount': str,
    'Total': str,
    'Fee': str,
    'Fee Coin': asset_regex,
  }

  @staticmethod
  def load(path: str, tz: timezone) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={'Price': str, 'Amount': str, 'Total': str, 'Fee': str})
    df.rename(columns=lambda c: str(c).lstrip('\ufeff'), inplace=True)
    util.validate_schema(df, spot_order_details.schema)
    df['Time(UTC)'] = pd.to_datetime(df['Date']).dt.tz_localize(tz).dt.tz_convert(timezone.utc)
    return df

  @staticmethod
  def parse(path: str, tz: timezone):
    df = spot_order_details.load(path, tz)
    yield from spot_order_details.parse_df(df)

  @staticmethod
  def parse_df(df: pd.DataFrame):
    for _, row in df.iterrows():
      yield SpotTrade(
        time=util.ensure_datetime(row['Time(UTC)']),
        base=str(row['Base Asset']),
        quote=str(row['Quote Asset']),
        qty=Decimal(str(row['Amount'])),
        price=Decimal(str(row['Price'])),
        liquidity=None,
        side='buy' if str(row['Direction']).lower() == 'buy' else 'sell',
        fee=abs(Decimal(str(row['Fee']))),
        fee_asset=str(row['Fee Coin']),
        raw=row.to_dict(),
        source='export:spot_order_details',
      )
