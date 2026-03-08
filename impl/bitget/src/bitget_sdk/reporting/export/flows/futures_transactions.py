from decimal import Decimal
from datetime import timezone
import re
import pandas as pd

from trading_sdk.reporting.history import Flow
import trading_sdk.util.csv as util

class futures_transactions:
  """Parsing Bitget's futures transactions export.

  Data must be downloaded as a CSV file from:

  > Bitget > Data Export > Futures > Futures Transactions

  **Expected schema:**

  - `Order`
  - `Date`
  - `Coin`
  - `Futures`
  - `Margin Mode`
  - `Type`
  - `Amount`
  - `Fee`
  - `Wallet balance`
  """

  asset_regex = re.compile(r'^[A-Z0-9]+$')
  futures_regex = re.compile(r'^(NULL|[A-Z0-9]+)$')

  schema: util.Schema = {
    'Order': str,
    'Date': str,
    'Coin': asset_regex,
    'Futures': futures_regex,
    'Margin Mode': str,
    'Type': str,
    'Amount': str,
    'Fee': str,
    'Wallet balance': str,
  }

  @staticmethod
  def load(path: str, tz: timezone) -> pd.DataFrame:
    df = pd.read_csv(
      path,
      dtype={
        'Order': str,
        'Coin': str,
        'Futures': str,
        'Margin Mode': str,
        'Type': str,
        'Amount': str,
        'Fee': str,
        'Wallet balance': str,
      },
      keep_default_na=False,
    )
    df.rename(columns=lambda c: str(c).lstrip('\ufeff'), inplace=True)
    util.validate_schema(df, futures_transactions.schema)
    df['Time(UTC)'] = pd.to_datetime(df['Date']).dt.tz_localize(tz).dt.tz_convert(timezone.utc)
    return df

  @staticmethod
  def parse(path: str, tz: timezone, *_, **__):
    df = futures_transactions.load(path, tz)
    yield from futures_transactions.parse_df(df)

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
        source='export:futures_transactions',
      )
      fee = abs(Decimal(str(row['Fee'])))
      if fee != 0:
        yield Flow(
          asset=str(row['Coin']),
          change=-fee,
          time=util.ensure_datetime(row['Time(UTC)']),
          event_tag='fee',
          raw=row.to_dict(),
          source='export:futures_transactions',
        )
