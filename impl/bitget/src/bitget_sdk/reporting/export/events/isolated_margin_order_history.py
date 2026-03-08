from decimal import Decimal
from datetime import timezone
import re
import pandas as pd

from trading_sdk.reporting.history import SpotTrade
import trading_sdk.util.csv as util

class isolated_margin_order_history:
  """Parsing Bitget's isolated margin order history export.

  Data must be downloaded as a CSV file from:

  > Bitget > Data Export > Margin > Isolated Margin Order History

  **Expected schema:**

  - `Date`
  - `Type`
  - `Business`
  - `Order ID`
  - `Trading Pair`
  - `Base Asset`
  - `Quote Asset`
  - `Direction`
  - `Price`
  - `Order amount`
  - `Average Price`
  - `Executed`
  - `Trading volume`
  - `Status`
  """

  pair_regex = re.compile(r'^[A-Z0-9]+/[A-Z0-9]+$')
  asset_regex = re.compile(r'^[A-Z0-9]+$')
  direction_regex = re.compile(r'^(buy|sell)$', re.IGNORECASE)
  status_regex = re.compile(r'^(fully executed|cancelled|partially executed)$', re.IGNORECASE)

  schema: util.Schema = {
    'Date': str,
    'Type': str,
    'Business': str,
    'Order ID': str,
    'Trading Pair': pair_regex,
    'Base Asset': asset_regex,
    'Quote Asset': asset_regex,
    'Direction': direction_regex,
    'Price': str,
    'Order amount': str,
    'Average Price': str,
    'Executed': str,
    'Trading volume': str,
    'Status': status_regex,
  }

  @staticmethod
  def load(path: str, tz: timezone) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={
      'Order ID': str,
      'Price': str,
      'Order amount': str,
      'Average Price': str,
      'Executed': str,
      'Trading volume': str,
    })
    df.rename(columns=lambda c: str(c).lstrip('\ufeff'), inplace=True)
    util.validate_schema(df, isolated_margin_order_history.schema)
    df['Time(UTC)'] = pd.to_datetime(df['Date'], errors='coerce').dt.tz_localize(tz).dt.tz_convert(timezone.utc)
    return df

  @staticmethod
  def parse(path: str, tz: timezone, *_, **__):
    df = isolated_margin_order_history.load(path, tz)
    yield from isolated_margin_order_history.parse_df(df)

  @staticmethod
  def parse_df(df: pd.DataFrame):
    for _, row in df.iterrows():
      if str(row['Date']) == 'Date':
        continue
      if pd.isna(row['Time(UTC)']):
        continue
      executed = Decimal(str(row['Executed']))
      if executed == 0:
        continue
      price = Decimal(str(row['Average Price']))
      if price == 0:
        price = Decimal(str(row['Price']))
      yield SpotTrade(
        id=str(row['Order ID']).lstrip(),
        time=util.ensure_datetime(row['Time(UTC)']),
        base=str(row['Base Asset']),
        quote=str(row['Quote Asset']),
        qty=executed,
        price=price,
        liquidity=None,
        side='buy' if str(row['Direction']).lower() == 'buy' else 'sell',
        fee=None,
        fee_asset=None,
        raw=row.to_dict(),
        source='export:isolated_margin_order_history',
      )
