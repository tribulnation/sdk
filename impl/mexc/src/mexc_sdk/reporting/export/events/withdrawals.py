from decimal import Decimal
from datetime import timezone
import pandas as pd

from trading_sdk.reporting.history import CryptoWithdrawal
import trading_sdk.util.csv as util

def parse_entry(row: pd.Series):
  asset = str(row['Crypto'])
  network = str(row['Network'])
  tx_hash, *rest = str(row['TxID']).split(':')
  idx = int(rest[0]) if rest else None
  memo = str(row['memo'])
  if memo == '--':
    memo = None

  return CryptoWithdrawal(
    asset=asset,
    qty=Decimal(str(row['Settlement Amount'])),
    tx_hash=tx_hash, idx=idx,
    network=network,
    time=util.ensure_datetime(row['Time(UTC)']),
    dst_address=str(row['Withdrawal Address']),
    dst_memo=memo,
    fee=Decimal(str(row['Trading Fee'])),
    fee_asset=asset,
    raw=row.to_dict(),
    source='export:withdrawals',
  )

class withdrawals:
  """Parsing MEXC's withdrawals log.

  *This data is already included in the spot statement.*

    It must be downloaded as an Excel file from:
    
    > [Data Export](https://www.mexc.com/support/data-export) > `Funding History` > `Withdrawal History` > `Excel`

    **Expected schema:**

    - `Status`
    - `Time`
    - `Crypto`
    - `Network`
    - `Settlement Amount`	
    - `Withdrawal Address`
    - `memo`
    - `Trading Fee`
    - `TxID`
    """

  schema: util.Schema = {
    'Status': str,
    'Time': str,
    'Crypto': str,
    'Network': str,
    'Settlement Amount': str,
    'Withdrawal Address': str,
    'memo': str,
    'Trading Fee': str,
    'TxID': str,
  }

  @staticmethod
  def load(path: str, tz: timezone) -> pd.DataFrame:
    df = pd.read_excel(path, dtype={'Settlement Amount': str, 'Trading Fee': str})
    util.validate_schema(df, withdrawals.schema)
    df.drop(df[df['Status'] != 'Withdrawal Successful'].index, inplace=True) # type: ignore
    df.reset_index(drop=True, inplace=True)
    df['Time(UTC)'] = pd.to_datetime(df['Time']).dt.tz_localize(tz).dt.tz_convert(timezone.utc)
    return df

  @staticmethod
  def parse(path: str, tz: timezone, *_, **__):
    """Parse withdrawals log excel file.

    - `path`: Path to excel file
    - `tz`: Timezone of the times in the log
    """
    df = withdrawals.load(path, tz)
    yield from withdrawals.parse_df(df)

  @staticmethod
  def parse_df(df: pd.DataFrame):
    for _, row in df.iterrows():
      yield parse_entry(row)