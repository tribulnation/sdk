from decimal import Decimal
from datetime import timezone
import re
import pandas as pd

from trading_sdk.reporting.history import Flow
import trading_sdk.util.csv as util

class spot_transactions:
  """Parsing Bitget's spot transactions export.

  Data must be downloaded as a CSV file from:

  > Bitget > Data Export > Spot > Spot Transactions

  **Expected schema:**

  - `order`
  - `Date`
  - `Coin`
  - `Type`
  - `Amount`
  - `Fee`
  - `Available`
  """

  asset_regex = re.compile(r'^[A-Z0-9]+$')

  schema: util.Schema = {
    'order': str,
    'Date': str,
    'Coin': asset_regex,
    'Type': str,
    'Amount': str,
    'Fee': str,
    'Available': str,
  }

  @staticmethod
  def load(path: str, tz: timezone) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={'Amount': str, 'Fee': str, 'Available': str, 'order': str})
    df.rename(columns=lambda c: str(c).lstrip('\ufeff'), inplace=True)
    util.validate_schema(df, spot_transactions.schema)
    df['Time(UTC)'] = pd.to_datetime(df['Date']).dt.tz_localize(tz).dt.tz_convert(timezone.utc)
    return df

  @staticmethod
  def parse(path: str, tz: timezone):
    df = spot_transactions.load(path, tz)
    yield from spot_transactions.parse_df(df)

  @staticmethod
  def parse_df(df: pd.DataFrame):
    for _, row in df.iterrows():
      amount = Decimal(str(row['Amount']))
      yield Flow(
        asset=str(row['Coin']),
        change=amount,
        time=util.ensure_datetime(row['Time(UTC)']),
        event_tag=str(row['Type']),
        raw=row.to_dict(),
        source='export:spot_transactions',
      )
      fee = abs(Decimal(str(row['Fee'])))
      if fee != 0:
        yield Flow(
          asset=str(row['Coin']),
          change=-fee,
          time=util.ensure_datetime(row['Time(UTC)']),
          event_tag='fee',
          raw=row.to_dict(),
          source='export:spot_transactions',
        )
