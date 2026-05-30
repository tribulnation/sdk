"""BigQuery-backed dYdX reporting history."""

from typing_extensions import TYPE_CHECKING
import asyncio
from datetime import datetime
from decimal import Decimal

from tribulnation.sdk.reporting import CryptoTransaction, Fee, Funding, InternalTransfer, Record, Transfer, Yield

from .accounts import megavault_account, staking_account, subaccount_account, wallet_account
from .coins import asset_symbol, denom_quantums, parse_coins, parse_fee_coin
from .constants import COMMUNITY_TREASURY_ADDRESS, USDC, USDC_QUANTUMS
from .time import parse_time
from ..util import source_id

if TYPE_CHECKING:
  from google.cloud.bigquery import Client as BigQueryClient
  from google.cloud.bigquery.query import ScalarQueryParameter

def row_decimal(row: dict[str, object], key: str) -> Decimal:
  """Read a BigQuery numeric value as a decimal."""
  return Decimal(str(row[key]))

def row_time(row: dict[str, object]) -> datetime:
  """Read a BigQuery block timestamp."""
  value = row['block_timestamp']
  if isinstance(value, datetime):
    return value
  return parse_time(str(value))

def row_int(row: dict[str, object], key: str) -> int:
  """Read a BigQuery integer value."""
  return int(str(row[key]))

def row_str(row: dict[str, object], key: str) -> str:
  """Read a BigQuery string value."""
  return str(row[key])

def row_str_from(row: dict[str, object], keys: list[str]) -> str:
  """Read the first present BigQuery string value from candidate keys."""
  value = first_row_value(row, keys)
  if value is None:
    raise KeyError(keys[0])
  return str(value)

def row_subaccount(value: object | None) -> str | int | None:
  """Read a BigQuery subaccount identifier."""
  if value is None:
    return None
  if isinstance(value, int):
    return value
  return str(value)

def first_row_value(row: dict[str, object], keys: list[str]) -> object | None:
  """Return the first present BigQuery row value without truthiness fallback."""
  for key in keys:
    if key in row and row[key] is not None:
      return row[key]
  return None

def bigquery_coin(row: dict[str, object], *, amount_key: str, denom_key: str) -> tuple[str, Decimal]:
  """Normalize a BigQuery amount and denom pair."""
  denom = row_str(row, denom_key)
  return asset_symbol(denom), row_decimal(row, amount_key) / denom_quantums(denom)

class BigQueryHistory:
  """BigQuery-backed dYdX history methods."""
  address: str
  bigquery: 'BigQueryClient | None'

  async def bigquery_rows(
    self, sql: str, *, parameters: list['ScalarQueryParameter'],
  ) -> list[dict[str, object]]:
    """Run a dYdX BigQuery query and return plain row dictionaries."""
    if self.bigquery is None:
      raise ValueError('dYdX reporting source requires BigQuery, but no BigQuery client is configured.')
    from google.cloud import bigquery
    client = self.bigquery
    def run() -> list[dict[str, object]]:
      """Execute the synchronous BigQuery client call in a worker thread."""
      job_config = bigquery.QueryJobConfig(query_parameters=parameters)
      return [dict(row) for row in client.query(sql, job_config=job_config).result()]
    return await asyncio.to_thread(run)

  def window_parameters(
    self, *, start: datetime | None, end: datetime | None,
  ) -> list['ScalarQueryParameter']:
    """Build common BigQuery parameters for account history queries."""
    from google.cloud import bigquery
    return [
      bigquery.ScalarQueryParameter('address', 'STRING', self.address),
      bigquery.ScalarQueryParameter('start', 'TIMESTAMP', start),
      bigquery.ScalarQueryParameter('end', 'TIMESTAMP', end),
    ]

  async def bigquery_funding(
    self, *, start: datetime | None, end: datetime | None,
  ) -> list[Record]:
    """Collect settled funding payments from Numia BigQuery."""
    rows = await self.bigquery_rows("""
      select *
      from `numia-data.dydx_mainnet.dydx_settled_funding`
      where subaccount = @address
        and (@start is null or block_timestamp >= @start)
        and (@end is null or block_timestamp <= @end)
      order by block_timestamp, block_height, tx_index, message_index, action_index
    """, parameters=self.window_parameters(start=start, end=end))
    return [self.parse_bigquery_funding(row) for row in rows]

  def parse_bigquery_funding(self, row: dict[str, object]) -> Record:
    """Convert one Numia settled funding row into an SDK funding record."""
    amount = -row_decimal(row, 'funding_paid_quote_quantums') / USDC_QUANTUMS
    row_id = f"{row_str(row, 'tx_hash')}:{row_int(row, 'message_index')}:{row_int(row, 'action_index')}"
    return Record(
      observations=[Funding(
        id=row_id,
        time=row_time(row),
        asset=USDC,
        amount=amount,
        subaccount=row_int(row, 'subaccount_number'),
      )],
      provenance={'source': 'api', 'service': 'dydx', 'id': source_id('dydx')},
    )

  async def bigquery_chain_fees(
    self, *, start: datetime | None, end: datetime | None,
  ) -> list[Record]:
    """Collect wallet-paid chain fees from Numia BigQuery transactions."""
    rows = await self.bigquery_rows("""
      select *
      from `numia-data.dydx_mainnet.dydx_transactions`
      where fee_payer = @address
        and fee_coins is not null
        and fee_coins != ''
        and (@start is null or block_timestamp >= @start)
        and (@end is null or block_timestamp <= @end)
      order by block_timestamp, block_height, tx_index
    """, parameters=self.window_parameters(start=start, end=end))
    records: list[Record] = []
    for row in rows:
      record = self.parse_bigquery_chain_fee(row)
      if record is not None:
        records.append(record)
    return records

  def parse_bigquery_chain_fee(self, row: dict[str, object]) -> Record | None:
    """Convert one Numia transaction row into a chain-fee record."""
    fee_value = row.get('fee_coins') or row.get('fee')
    if fee_value is None:
      return None
    fee_asset, fee_amount = parse_fee_coin(str(fee_value))
    tx_id = row_str(row, 'tx_id')
    return Record(
      observations=[CryptoTransaction(
        id=tx_id,
        time=row_time(row),
        tx_id=tx_id,
        fee=Fee(asset=fee_asset, amount=fee_amount),
      )],
      provenance={'source': 'api', 'service': 'dydx', 'id': source_id('dydx')},
    )

  async def bigquery_subaccount_transfers(
    self, *, start: datetime | None, end: datetime | None,
  ) -> list[Record]:
    """Collect subaccount deposits, withdrawals, and transfers from Numia BigQuery."""
    deposits, withdrawals, transfers = await asyncio.gather(
      self.bigquery_subaccount_table('dydx_deposit', start=start, end=end),
      self.bigquery_subaccount_table('dydx_withdrawal', start=start, end=end),
      self.bigquery_subaccount_table('dydx_transfer', start=start, end=end),
    )
    return deposits + withdrawals + transfers

  async def bigquery_subaccount_table(
    self, table: str, *, start: datetime | None, end: datetime | None,
  ) -> list[Record]:
    """Collect one Numia subaccount transfer table by address."""
    rows = await self.bigquery_rows(f"""
      select *
      from `numia-data.dydx_mainnet.{table}`
      where (
        sender = @address
        or recipient = @address
      )
        and (@start is null or block_timestamp >= @start)
        and (@end is null or block_timestamp <= @end)
      order by block_timestamp, block_height, tx_index, message_index, action_index
    """, parameters=self.window_parameters(start=start, end=end))
    records: list[Record] = []
    for row in rows:
      record = self.parse_bigquery_subaccount_transfer(row, table=table)
      if record is not None:
        records.append(record)
    return records

  def parse_bigquery_subaccount_transfer(self, row: dict[str, object], *, table: str) -> Record | None:
    """Convert one Numia subaccount row into an internal transfer."""
    amount_value = row.get('quantums') or row.get('quote_quantums') or row.get('amount')
    if amount_value is None:
      return None
    amount = Decimal(str(amount_value)) / USDC_QUANTUMS
    sender = str(row.get('sender') or self.address)
    recipient = str(row.get('recipient') or self.address)
    sender_number = row_subaccount(first_row_value(
      row,
      ['sender_number', 'sender_subaccount', 'sender_subaccount_number', 'subaccount_number'],
    ))
    recipient_number = row_subaccount(first_row_value(
      row,
      ['recipient_number', 'recipient_subaccount', 'recipient_subaccount_number', 'subaccount_number'],
    ))
    if table == 'dydx_deposit':
      src_account = wallet_account(sender)
      dst_account = subaccount_account(recipient, recipient_number)
    elif table == 'dydx_withdrawal':
      src_account = subaccount_account(sender, sender_number)
      dst_account = wallet_account(recipient)
    else:
      src_account = subaccount_account(sender, sender_number)
      dst_account = subaccount_account(recipient, recipient_number)
    row_id = f"{row_str(row, 'tx_hash')}:{table}:{row_int(row, 'message_index')}:{row_int(row, 'action_index')}"
    return Record(
      observations=[InternalTransfer(
        id=row_id,
        time=row_time(row),
        asset=USDC,
        amount=amount,
        src_account=src_account,
        dst_account=dst_account,
      )],
      provenance={'source': 'api', 'service': 'dydx', 'id': source_id('dydx')},
    )

  async def bigquery_staking_transfers(
    self, *, start: datetime | None, end: datetime | None,
  ) -> list[Record]:
    """Collect staking allocation movements and reward withdrawals from Numia BigQuery."""
    delegates, undelegates, rewards = await asyncio.gather(
      self.bigquery_delegate_transfers(start=start, end=end),
      self.bigquery_undelegate_transfers(start=start, end=end),
      self.bigquery_staking_rewards(start=start, end=end),
    )
    return delegates + undelegates + rewards

  async def bigquery_delegate_transfers(
    self, *, start: datetime | None, end: datetime | None,
  ) -> list[Record]:
    """Collect delegation movements from Numia BigQuery."""
    rows = await self.bigquery_rows("""
      select *
      from `numia-data.dydx_mainnet.dydx_delegate`
      where sender = @address
        and (@start is null or block_timestamp >= @start)
        and (@end is null or block_timestamp <= @end)
      order by block_timestamp, block_height, tx_index, message_index, action_index
    """, parameters=self.window_parameters(start=start, end=end))
    return [self.parse_bigquery_staking_transfer(row, kind='delegate') for row in rows]

  async def bigquery_undelegate_transfers(
    self, *, start: datetime | None, end: datetime | None,
  ) -> list[Record]:
    """Collect undelegation completion movements from Numia BigQuery."""
    rows = await self.bigquery_rows("""
      select *
      from `numia-data.dydx_mainnet.dydx_undelegate`
      where sender = @address
        and (@start is null or timestamp(completion_time) >= @start)
        and (@end is null or timestamp(completion_time) <= @end)
      order by timestamp(completion_time), block_height, tx_index, message_index, action_index
    """, parameters=self.window_parameters(start=start, end=end))
    return [self.parse_bigquery_staking_transfer(row, kind='undelegate') for row in rows]

  def parse_bigquery_staking_transfer(self, row: dict[str, object], *, kind: str) -> Record:
    """Convert a Numia delegate or undelegate row into an internal transfer."""
    asset, amount = bigquery_coin(row, amount_key='token_amount', denom_key='token_denom')
    validator = row_str(row, 'validator')
    if kind == 'delegate':
      time = row_time(row)
      src_account = wallet_account(self.address)
      dst_account = staking_account(self.address, validator=validator)
    else:
      completion_time = row.get('completion_time')
      time = parse_time(str(completion_time)) if completion_time is not None else row_time(row)
      src_account = staking_account(self.address, validator=validator)
      dst_account = wallet_account(self.address)
    row_id = f"{row_str(row, 'tx_hash')}:{kind}:{row_int(row, 'message_index')}:{row_int(row, 'action_index')}"
    return Record(
      observations=[InternalTransfer(
        id=row_id,
        time=time,
        asset=asset,
        amount=amount,
        src_account=src_account,
        dst_account=dst_account,
      )],
      provenance={'source': 'api', 'service': 'dydx', 'id': source_id('dydx')},
    )

  async def bigquery_staking_rewards(
    self, *, start: datetime | None, end: datetime | None,
  ) -> list[Record]:
    """Collect staking reward withdrawals from Numia message events."""
    rows = await self.bigquery_rows("""
      select *
      from `numia-data.dydx_mainnet.dydx_message_events`
      where event_type = 'withdraw_rewards'
        and json_value(event_attributes, '$.delegator') = @address
        and (@start is null or block_timestamp >= @start)
        and (@end is null or block_timestamp <= @end)
      order by block_timestamp, block_height, tx_index, message_index, event_index
    """, parameters=self.window_parameters(start=start, end=end))
    records: list[Record] = []
    for row in rows:
      record = self.parse_bigquery_staking_reward(row)
      if record is not None:
        records.append(record)
    return records

  def parse_bigquery_staking_reward(self, row: dict[str, object]) -> Record | None:
    """Convert one Numia staking reward event into yield observations."""
    attributes = row.get('event_attributes')
    if not isinstance(attributes, dict):
      return None
    if attributes.get('delegator') != self.address:
      return None
    amount_value = attributes.get('amount')
    if amount_value is None:
      return None
    observations: list[Yield] = []
    row_id = f"{row_str_from(row, ['tx_hash', 'tx_id'])}:withdraw_rewards:{row_int(row, 'event_index')}"
    for coin_index, (asset, amount) in enumerate(parse_coins(str(amount_value))):
      if amount == 0:
        continue
      observations.append(Yield(
        id=f'{row_id}:{coin_index}',
        time=row_time(row),
        asset=asset,
        amount=amount,
      ))
    if not observations:
      return None
    return Record(
      observations=observations,
      provenance={'source': 'api', 'service': 'dydx', 'id': source_id('dydx')},
    )

  async def bigquery_trading_rewards(
    self, *, start: datetime | None, end: datetime | None,
  ) -> list[Record]:
    """Collect trading reward distributions from Numia BigQuery."""
    rows = await self.bigquery_rows("""
      select *
      from `numia-data.dydx_mainnet.dydx_reward_distribution`
      where recipient = @address
        and (@start is null or block_timestamp >= @start)
        and (@end is null or block_timestamp <= @end)
      order by block_timestamp, block_height, action_index
    """, parameters=self.window_parameters(start=start, end=end))
    return [self.parse_bigquery_trading_reward(row) for row in rows]

  def parse_bigquery_trading_reward(self, row: dict[str, object]) -> Record:
    """Convert a Numia reward distribution row into a yield observation."""
    asset, amount = bigquery_coin(row, amount_key='token_amount', denom_key='token_denom')
    row_id = f"{row_int(row, 'block_height')}:{row_int(row, 'action_index')}"
    return Record(
      observations=[Yield(
        id=row_id,
        time=row_time(row),
        asset=asset,
        amount=amount,
      )],
      provenance={'source': 'api', 'service': 'dydx', 'id': source_id('dydx')},
    )

  async def bigquery_community_treasury_distributions(
    self, *, start: datetime | None, end: datetime | None,
  ) -> list[Record]:
    """Collect Community Treasury distributions from raw Numia block events."""
    rows = await self.bigquery_rows("""
      select *
      from `numia-data.dydx_mainnet.dydx_block_events`
      where event_type = 'transfer'
        and json_value(event_attributes, '$.mode') = 'EndBlock'
        and json_value(event_attributes, '$.recipient') = @address
        and json_value(event_attributes, '$.sender') = @treasury
        and (@start is null or block_timestamp >= @start)
        and (@end is null or block_timestamp <= @end)
      order by block_timestamp, block_height, event_index
    """, parameters=self.window_parameters(start=start, end=end) + [self.string_parameter('treasury', COMMUNITY_TREASURY_ADDRESS)])
    records: list[Record] = []
    for row in rows:
      record = self.parse_bigquery_community_treasury_distribution(row)
      if record is not None:
        records.append(record)
    return records

  def parse_bigquery_community_treasury_distribution(self, row: dict[str, object]) -> Record | None:
    """Convert one raw Community Treasury transfer into yield observations."""
    attributes = row.get('event_attributes')
    if not isinstance(attributes, dict):
      return None
    if attributes.get('sender') != COMMUNITY_TREASURY_ADDRESS or attributes.get('recipient') != self.address:
      return None
    amount_value = attributes.get('amount')
    if amount_value is None:
      return None
    observations: list[Yield] = []
    row_id = f"{row_int(row, 'block_height')}:{row_int(row, 'event_index')}"
    for coin_index, (asset, amount) in enumerate(parse_coins(str(amount_value))):
      observations.append(Yield(
        id=f'{row_id}:community_treasury:{coin_index}',
        time=row_time(row),
        asset=asset,
        amount=amount,
      ))
    if not observations:
      return None
    return Record(
      observations=observations,
      provenance={'source': 'api', 'service': 'dydx', 'id': source_id('dydx')},
    )

  async def bigquery_megavault_transfers(
    self, *, start: datetime | None, end: datetime | None,
  ) -> list[Record]:
    """Collect Megavault deposits and withdrawals from Numia message events."""
    rows = await self.bigquery_rows("""
      select *
      from `numia-data.dydx_mainnet.dydx_message_events`
      where event_type in ('deposit_to_megavault', 'withdraw_from_megavault')
        and to_json_string(event_attributes) like concat('%', @address, '%')
        and (@start is null or block_timestamp >= @start)
        and (@end is null or block_timestamp <= @end)
      order by block_timestamp, block_height, tx_index, message_index, event_index
    """, parameters=self.window_parameters(start=start, end=end))
    records: list[Record] = []
    for row in rows:
      record = self.parse_bigquery_megavault_transfer(row)
      if record is not None:
        records.append(record)
    return records

  def parse_bigquery_megavault_transfer(self, row: dict[str, object]) -> Record | None:
    """Convert one Numia Megavault event row into an internal transfer."""
    event_type = str(row.get('event_type') or '')
    attributes = row.get('event_attributes')
    if not isinstance(attributes, dict):
      return None
    if event_type == 'deposit_to_megavault':
      if attributes.get('depositor') != self.address:
        return None
      amount_value = attributes.get('quote_quantums')
      src_account = subaccount_account(self.address, 0)
      dst_account = megavault_account(self.address)
      kind = 'deposit_to_megavault'
      sign = Decimal(-1)
    elif event_type == 'withdraw_from_megavault':
      if attributes.get('withdrawer') != self.address:
        return None
      amount_value = attributes.get('redeemed_quote_quantums')
      src_account = megavault_account(self.address)
      dst_account = subaccount_account(self.address, 0)
      kind = 'withdraw_from_megavault'
      sign = Decimal(1)
    else:
      return None
    if amount_value is None:
      return None
    amount = Decimal(str(amount_value)) / USDC_QUANTUMS * sign
    row_id = f"{row_str_from(row, ['tx_hash', 'tx_id'])}:{kind}:{row_int(row, 'event_index')}"
    return Record(
      observations=[Transfer(
        id=row_id,
        time=row_time(row),
        asset=USDC,
        amount=amount,
        src_account=src_account,
        dst_account=dst_account,
      )],
      provenance={'source': 'api', 'service': 'dydx', 'id': source_id('dydx')},
    )

  async def bigquery_ibc_wallet_transfers(
    self, *, start: datetime | None, end: datetime | None,
  ) -> list[Record]:
    """Collect IBC wallet transfers from Numia message events."""
    rows = await self.bigquery_rows("""
      select *
      from `numia-data.dydx_mainnet.dydx_message_events`
      where event_type in ('ibc_transfer', 'fungible_token_packet')
        and to_json_string(event_attributes) like concat('%', @address, '%')
        and (@start is null or block_timestamp >= @start)
        and (@end is null or block_timestamp <= @end)
      order by block_timestamp, block_height, tx_index, message_index, event_index
    """, parameters=self.window_parameters(start=start, end=end))
    records: list[Record] = []
    for row in rows:
      record = self.parse_bigquery_ibc_wallet_transfer(row)
      if record is not None:
        records.append(record)
    return records

  def parse_bigquery_ibc_wallet_transfer(self, row: dict[str, object]) -> Record | None:
    """Convert one Numia IBC event row into an account transfer."""
    event_type = str(row.get('event_type') or '')
    attributes = row.get('event_attributes')
    if not isinstance(attributes, dict):
      return None
    denom = attributes.get('denom')
    amount_value = attributes.get('amount')
    if denom is None or amount_value is None:
      return None
    asset, amount = parse_fee_coin(f'{amount_value}{denom}')
    sender = attributes.get('sender')
    receiver = attributes.get('receiver')
    if event_type == 'ibc_transfer' and sender == self.address:
      signed = -amount
    elif event_type == 'fungible_token_packet' and receiver == self.address and attributes.get('success') != 'false':
      signed = amount
    else:
      return None
    row_id = f"{row_str_from(row, ['tx_hash', 'tx_id'])}:ibc:{row_int(row, 'event_index')}"
    return Record(
      observations=[Transfer(
        id=row_id,
        time=row_time(row),
        asset=asset,
        amount=signed,
        src_account=str(sender) if sender is not None else None,
        dst_account=str(receiver) if receiver is not None else None,
      )],
      provenance={'source': 'api', 'service': 'dydx', 'id': source_id('dydx')},
    )

  async def bigquery_wallet_transfers(
    self, *, start: datetime | None, end: datetime | None,
  ) -> list[Record]:
    """Collect unmatched wallet-level transfers from Numia message events."""
    rows = await self.bigquery_rows("""
      with known as (
        select distinct tx_hash
        from `numia-data.dydx_mainnet.dydx_message_events`
        where event_type in (
          'ibc_transfer',
          'fungible_token_packet',
          'deposit_to_subaccount',
          'withdraw_from_subaccount',
          'create_transfer',
          'deposit_to_megavault',
          'withdraw_from_megavault',
          'withdraw_rewards'
        )
          and to_json_string(event_attributes) like concat('%', @address, '%')
        union distinct
        select distinct tx_id as tx_hash
        from `numia-data.dydx_mainnet.dydx_transactions`
        where fee_payer = @address
      )
      select *
      from `numia-data.dydx_mainnet.dydx_message_events`
      where event_type = 'transfer'
        and (
          json_value(event_attributes, '$.recipient') = @address
          or json_value(event_attributes, '$.sender') = @address
        )
        and tx_hash not in (select tx_hash from known)
        and (@start is null or block_timestamp >= @start)
        and (@end is null or block_timestamp <= @end)
      order by block_timestamp, block_height, tx_index, message_index, event_index
    """, parameters=self.window_parameters(start=start, end=end))
    records: list[Record] = []
    for row in rows:
      record = self.parse_bigquery_wallet_transfer(row)
      if record is not None:
        records.append(record)
    return records

  def parse_bigquery_wallet_transfer(self, row: dict[str, object]) -> Record | None:
    """Convert one unmatched wallet transfer event into transfer observations."""
    attributes = row.get('event_attributes')
    if not isinstance(attributes, dict):
      return None
    sender = attributes.get('sender')
    recipient = attributes.get('recipient')
    amount_value = attributes.get('amount')
    if amount_value is None:
      return None
    if recipient == self.address:
      sign = Decimal(1)
    elif sender == self.address:
      sign = Decimal(-1)
    else:
      return None
    observations: list[Transfer] = []
    row_id = f"{row_str_from(row, ['tx_hash', 'tx_id'])}:wallet_transfer:{row_int(row, 'event_index')}"
    for coin_index, (asset, amount) in enumerate(parse_coins(str(amount_value))):
      if amount == 0 or asset != USDC:
        continue
      observations.append(Transfer(
        id=f'{row_id}:{coin_index}',
        time=row_time(row),
        asset=asset,
        amount=amount * sign,
        src_account=str(sender) if sender is not None else None,
        dst_account=str(recipient) if recipient is not None else None,
      ))
    if not observations:
      return None
    return Record(
      observations=observations,
      provenance={'source': 'api', 'service': 'dydx', 'id': source_id('dydx')},
    )

  def string_parameter(self, name: str, value: str) -> 'ScalarQueryParameter':
    """Build a BigQuery string parameter."""
    from google.cloud import bigquery
    return bigquery.ScalarQueryParameter(name, 'STRING', value)

  async def bigquery_native_wallet_transfers(
    self, *, start: datetime | None, end: datetime | None,
  ) -> list[Record]:
    """Collect native dYdX wallet transfers from raw Numia block events."""
    rows = await self.bigquery_rows("""
      select *
      from `numia-data.dydx_mainnet.dydx_block_events`
      where event_type = 'transfer'
        and json_value(event_attributes, '$.mode') = 'EndBlock'
        and (
          json_value(event_attributes, '$.recipient') = @address
          or json_value(event_attributes, '$.sender') = @address
        )
        and (@start is null or block_timestamp >= @start)
        and (@end is null or block_timestamp <= @end)
      order by block_timestamp, block_height, event_index
    """, parameters=self.window_parameters(start=start, end=end))
    records: list[Record] = []
    for row in rows:
      record = self.parse_bigquery_native_wallet_transfer(row)
      if record is not None:
        records.append(record)
    return records

  def parse_bigquery_native_wallet_transfer(self, row: dict[str, object]) -> Record | None:
    """Convert one raw block transfer event touching the wallet into an internal transfer."""
    attributes = row.get('event_attributes')
    if not isinstance(attributes, dict):
      return None
    sender = attributes.get('sender')
    recipient = attributes.get('recipient')
    amount_value = attributes.get('amount')
    if amount_value is None:
      return None
    if recipient != self.address and sender != self.address:
      return None
    records: list[InternalTransfer] = []
    row_id = f"{row_int(row, 'block_height')}:{row_int(row, 'event_index')}"
    for coin_index, (asset, amount) in enumerate(parse_coins(str(amount_value))):
      records.append(InternalTransfer(
        id=f'{row_id}:{coin_index}',
        time=row_time(row),
        asset=asset,
        amount=amount,
        src_account=str(sender) if sender is not None else None,
        dst_account=str(recipient) if recipient is not None else None,
      ))
    if not records:
      return None
    return Record(
      observations=records,
      provenance={'source': 'api', 'service': 'dydx', 'id': source_id('dydx')},
    )
