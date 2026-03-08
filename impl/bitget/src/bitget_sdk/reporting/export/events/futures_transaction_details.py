from decimal import Decimal
from datetime import timezone
import re
import pandas as pd

from trading_sdk.reporting.history import FuturesTrade
import trading_sdk.util.csv as util

class futures_transaction_details:
  """Parsing Bitget's futures transaction details export.

  Data must be downloaded as a CSV file from:

  > Bitget > Data Export > Futures > Futures Transaction Details

  **Expected schema:**

  - `Date`
  - `Direction`
  - `Coin`
  - `Futures`
  - `Transaction amount`
  - `Average Price`
  - `Trading volume`
  - `Realized P/L`
  - `NetProfits`
  - `Fee`
  """

  direction_regex = re.compile(r'^(open|close) (long|short)$|^liquidation for (long|short)$', re.IGNORECASE)
  asset_regex = re.compile(r'^[A-Z0-9]+$')
  futures_regex = re.compile(r'^(NULL|[A-Z0-9]+)$')

  schema: util.Schema = {
    'Date': str,
    'Direction': direction_regex,
    'Coin': asset_regex,
    'Futures': futures_regex,
    'Transaction amount': str,
    'Average Price': str,
    'Trading volume': str,
    'Realized P/L': str,
    'NetProfits': str,
    'Fee': str,
  }

  @staticmethod
  def load(path: str, tz: timezone) -> pd.DataFrame:
    df = pd.read_csv(
      path,
      dtype={
        'Coin': str,
        'Futures': str,
        'Transaction amount': str,
        'Average Price': str,
        'Trading volume': str,
        'Realized P/L': str,
        'NetProfits': str,
        'Fee': str,
      },
      keep_default_na=False,
    )
    df.rename(columns=lambda c: str(c).lstrip('\ufeff'), inplace=True)
    util.validate_schema(df, futures_transaction_details.schema)
    df['Time(UTC)'] = pd.to_datetime(df['Date']).dt.tz_localize(tz).dt.tz_convert(timezone.utc)
    return df

  @staticmethod
  def parse(path: str, tz: timezone, *_, **__):
    df = futures_transaction_details.load(path, tz)
    yield from futures_transaction_details.parse_df(df)

  @staticmethod
  def parse_df(df: pd.DataFrame):
    for _, row in df.iterrows():
      direction = str(row['Direction']).strip().lower()
      direction_map = {
        'open long': 'buy',
        'close long': 'sell',
        'liquidation for long': 'sell',
        'open short': 'sell',
        'close short': 'buy',
        'liquidation for short': 'buy',
      }
      side = direction_map.get(direction)
      assert side is not None

      fee = abs(Decimal(str(row['Fee'])))
      if fee == 0:
        fee = None

      yield FuturesTrade(
        time=util.ensure_datetime(row['Time(UTC)']),
        instrument=str(row['Futures']),
        qty=Decimal(str(row['Transaction amount'])),
        price=Decimal(str(row['Average Price'])),
        liquidity=None,
        side=side,
        fee=fee,
        fee_asset=str(row['Coin']) if fee is not None else None,
        raw=row.to_dict(),
        source='export:futures_transaction_details',
      )
