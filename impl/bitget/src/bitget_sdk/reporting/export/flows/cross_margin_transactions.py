from decimal import Decimal
from datetime import timezone
import re
import pandas as pd

from trading_sdk.reporting.history import Flow
import trading_sdk.util.csv as util

class cross_margin_transactions:
  """Parsing Bitget's cross margin transactions export.

  Data must be downloaded as a CSV file from:

  > Bitget > Data Export > Margin > Cross Margin Transactions

  **Expected schema:**

  - `Time`
  - `Pair`
  - `Coin`
  - `Type`
  - `Amount`
  - `fee`
  - `Balance`
  """

  pair_regex = re.compile(r'^(N/A|[A-Z0-9]+/[A-Z0-9]+)$')
  asset_regex = re.compile(r'^[A-Z0-9]+$')

  schema: util.Schema = {
    'Time': str,
    'Pair': pair_regex,
    'Coin': asset_regex,
    'Type': str,
    'Amount': str,
    'fee': str,
    'Balance': str,
  }

  @staticmethod
  def load(path: str, tz: timezone) -> pd.DataFrame:
    df = pd.read_csv(
      path,
      dtype={'Amount': str, 'fee': str, 'Balance': str, 'Pair': str, 'Coin': str},
      keep_default_na=False,
    )
    df.rename(columns=lambda c: str(c).lstrip('\ufeff'), inplace=True)
    util.validate_schema(df, cross_margin_transactions.schema)
    df['Time(UTC)'] = pd.to_datetime(df['Time']).dt.tz_localize(tz).dt.tz_convert(timezone.utc)
    return df

  @staticmethod
  def parse(path: str, tz: timezone, *_, **__):
    df = cross_margin_transactions.load(path, tz)
    yield from cross_margin_transactions.parse_df(df)

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
        source='export:cross_margin_transactions',
      )
      fee = abs(Decimal(str(row['fee'])))
      if fee != 0:
        yield Flow(
          asset=str(row['Coin']),
          change=-fee,
          time=util.ensure_datetime(row['Time(UTC)']),
          event_tag='fee',
          raw=row.to_dict(),
          source='export:cross_margin_transactions',
        )
