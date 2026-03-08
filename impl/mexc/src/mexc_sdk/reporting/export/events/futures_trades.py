from decimal import Decimal
from datetime import timezone, timedelta
import re
import pandas as pd

from trading_sdk.reporting.history import FuturesTrade
import trading_sdk.util.csv as util

time_regex = re.compile(r'Time\(UTC\+(\d{2}):(\d{2})\)')

def parse_timezone(key: str) -> timezone:
  match = time_regex.match(key)
  assert match is not None
  hours, minutes = match.groups()
  return timezone(timedelta(hours=int(hours), minutes=int(minutes)))

pair_regex = re.compile(r'^(.+?)(USDT|USDC)$')

def parse_entry(row: pd.Series):
  return FuturesTrade(
    instrument=f'{str(row["base"])}_{str(row["quote"])}',
    time=util.ensure_datetime(row['Time(UTC)']),
    qty=Decimal(str(row['Filled Qty (Crypto)'])),
    price=Decimal(str(row['Filled Price'])),
    liquidity='taker' if row['Role'] == 'Taker' else 'maker',
    side='buy' if row['Direction'] in ('sell short', 'buy long') else 'sell',
    fee=Decimal(str(row['Trading Fee'])),
    fee_asset=str(row['Fee-payment Crypto']),
    raw=row.to_dict(),
    source='export:futures_trades',
  )

class futures_trades:
  """Parsing MEXC's futures trades log.

  *This data is already included in the futures capital flow.*

    It must be downloaded as an Excel file from:
    
    > [Data Export](https://www.mexc.com/support/data-export) > `Futures` > `Futures Trade History` > `Excel`

    **Expected schema:**

    - `Time(<timezone>)`, e.g. `'Time(UTC+03:00)'`
    - `Futures Trading Pair, e.g. 'BTCUSDT'`	
    - `Direction :: 'sell short' | 'buy short' | 'sell long' | 'buy long'`
    - `Filled Qty (Crypto)`
    - `Filled Price`
    - `Trading Fee`
    - `Fee-payment Crypto`
    - `Role :: Taker | Maker`
    """

  schema: util.Schema = {
    time_regex: str,
    'Futures Trading Pair': pair_regex,
    'Direction': re.compile(r"^(sell short|buy short|sell long|buy long)$"),
    'Filled Qty (Crypto)': str,
    'Filled Price': str,
    'Trading Fee': str,
    'Fee-payment Crypto': str,
    'Role': re.compile(r"^(Taker|Maker)$"),
  }

  @staticmethod
  def load(path: str) -> pd.DataFrame:
    df = pd.read_excel(path, dtype={'Filled Qty (Crypto)': str, 'Filled Price': str, 'Trading Fee': str})
    util.validate_schema(df, futures_trades.schema)
    df[['base', 'quote']] = df['Futures Trading Pair'].str.extract(pair_regex)
    key = util.find_key(df, time_regex)
    assert key is not None
    df['Time(UTC)'] = pd.to_datetime(df[key]).dt.tz_localize(parse_timezone(key)).dt.tz_convert(timezone.utc)
    return df

  @staticmethod
  def parse(path: str, *_, **__):
    """Parse spot trades history excel file.

    - `path`: Path to excel file
    - `tz`: Timezone of the times in the log
    """
    df = futures_trades.load(path)
    yield from futures_trades.parse_df(df)

  @staticmethod
  def parse_df(df: pd.DataFrame):
    for _, row in df.iterrows():
      yield parse_entry(row)