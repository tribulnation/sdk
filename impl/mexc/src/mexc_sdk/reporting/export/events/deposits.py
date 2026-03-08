from decimal import Decimal
from datetime import timezone
import pandas as pd

from trading_sdk.reporting.history import CryptoDeposit
import trading_sdk.util.csv as util

def parse_entry(row: pd.Series):
  tx_hash, *rest = str(row['TxID']).split(':')
  idx = int(rest[0]) if rest else None
  network = str(row['Network'])
  return CryptoDeposit(
    asset=str(row['Crypto']),
    qty=Decimal(str(row['Deposit Amount'])),
    tx_hash=tx_hash,
    idx=idx,
    network=network,
    time=util.ensure_datetime(row['Time(UTC)']),
    raw=row.to_dict(),
    source='export:deposit_history',
  )

class deposits:
  """Parsing MEXC's (crypto) deposits log.

  *This data is already included in the spot statement.*

    It must be downloaded as an Excel file from:
    
    > [Data Export](https://www.mexc.com/support/data-export) > `Funding History` > `Deposit History` > `Excel`

    **Expected schema:**

    - `Status`
    - `Time`
    - `Crypto`
    - `Network`
    - `Deposit Amount`	
    - `TxID`
    """

  schema: util.Schema = {
    'Status': str,
    'Time': str,
    'Crypto': str,
    'Network': str,
    'Deposit Amount': str,
    'TxID': str,
  }

  @staticmethod
  def load(path: str, tz: timezone) -> pd.DataFrame:
    df = pd.read_excel(path, dtype={'Deposit Amount': str})
    util.validate_schema(df, deposits.schema)
    df.drop(df[df['Status'] != 'Credited Successfully'].index, inplace=True) # type: ignore
    df.reset_index(drop=True, inplace=True)
    df['Time(UTC)'] = pd.to_datetime(df['Time']).dt.tz_localize(tz).dt.tz_convert(timezone.utc)
    return df

  @staticmethod
  def parse(path: str, tz: timezone):
    """Parse deposits log excel file.

    - `path`: Path to excel file
    - `tz`: Timezone of the times in the log
    """
    df = deposits.load(path, tz)
    yield from deposits.parse_df(df)

  @staticmethod
  def parse_df(df: pd.DataFrame):
    for _, row in df.iterrows():
      yield parse_entry(row)