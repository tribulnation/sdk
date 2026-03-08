from decimal import Decimal
from datetime import timezone
import re
import pandas as pd

from trading_sdk.reporting.history import CryptoDeposit, CryptoWithdrawal
import trading_sdk.util.csv as util

class withdrawal_records:
  """Parsing Bitget's withdrawal records export.

  Data must be downloaded as a CSV file from:

  > Bitget > Data Export > Funding > Withdrawal Records

  **Expected schema:**

  - `Date`
  - `Type`
  - `Funding account`
  - `Coin`
  - `Quantity`
  - `Address`
  - `TxID`
  - `Status`
  """

  type_regex = re.compile(r'^(Deposit|Withdraw)$', re.IGNORECASE)
  asset_regex = re.compile(r'^[A-Z0-9]+$')
  status_regex = re.compile(r'^Successful$', re.IGNORECASE)

  schema: util.Schema = {
    'Date': str,
    'Type': type_regex,
    'Funding account': str,
    'Coin': asset_regex,
    'Quantity': str,
    'Address': str,
    'TxID': str,
    'Status': status_regex,
  }

  @staticmethod
  def load(path: str, tz: timezone) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={'Quantity': str, 'TxID': str})
    df.rename(columns=lambda c: str(c).lstrip('\ufeff'), inplace=True)
    util.validate_schema(df, withdrawal_records.schema)
    df = df[df['Status'] == 'Successful'].copy()
    df.reset_index(drop=True, inplace=True)
    df['Time(UTC)'] = pd.to_datetime(df['Date']).dt.tz_localize(tz).dt.tz_convert(timezone.utc)
    return df

  @staticmethod
  def parse(path: str, tz: timezone, *_, **__):
    df = withdrawal_records.load(path, tz)
    yield from withdrawal_records.parse_df(df)

  @staticmethod
  def parse_df(df: pd.DataFrame):
    for _, row in df.iterrows():
      if row['Type'] == 'Deposit':
        yield CryptoDeposit(
          asset=str(row['Coin']),
          qty=Decimal(str(row['Quantity'])),
          network='on_chain',
          tx_hash=str(row['TxID']),
          time=util.ensure_datetime(row['Time(UTC)']),
          raw=row.to_dict(),
          source='export:withdrawal_records',
        )
      elif row['Type'] == 'Withdraw':
        yield CryptoWithdrawal(
          asset=str(row['Coin']),
          qty=Decimal(str(row['Quantity'])),
          network='on_chain',
          tx_hash=str(row['TxID']),
          time=util.ensure_datetime(row['Time(UTC)']),
          dst_address=str(row['Address']),
          fee=None,
          fee_asset=None,
          raw=row.to_dict(),
          source='export:withdrawal_records',
        )
