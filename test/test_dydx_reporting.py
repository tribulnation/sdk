"""dYdX reporting adapter tests."""

import asyncio
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from typing_extensions import Literal

from tribulnation.dydx import Reporting
from tribulnation.dydx.report.history.accounts import account_label
from tribulnation.dydx.report.history.coins import parse_coins, parse_fee_coin
from tribulnation.dydx.report.history.comet import event_attributes
from tribulnation.dydx.report.history.constants import COMMUNITY_TREASURY_ADDRESS
from tribulnation.dydx.report.history.time import in_window
from dydx.indexer.data.get_fills import Fill
from dydx.indexer.data.get_subaccounts import Subaccount
from dydx.chain.comet.types import TxResponse
from dydx.node import DYDX_MAINNET_USDC_DENOM
from dydx.protos.cosmos.bank import v1beta1 as bank_proto
from dydx.protos.cosmos.base import v1beta1 as coin_proto
from dydx.protos.cosmos.distribution import v1beta1 as distribution_proto
from dydx.protos.cosmos.staking import v1beta1 as staking_proto
from tribulnation.sdk.reporting import (
  CryptoTransaction,
  Funding,
  FutureTrade,
  InternalTransfer,
  Record,
  Report,
  ReportSDK,
  Transfer,
  UnknownObservation,
  Yield,
)

NOW = datetime(2026, 5, 13, 12, tzinfo=timezone.utc)
ADDRESS = 'dydx1nn42jj4kjcr26xl9fghc0ce34335x9f3wfjp2a'

class FakeComet:
  """Fake Comet client for chain-evidence conversion tests."""

  async def block(self, height: int, validate: bool | None = None):
    """Return a minimal block response."""
    return {'block': {'header': {'time': NOW}}}

class FakePaging:
  """Fake typed-dydx paginated response."""
  init: int = 1

  async def next(self, state: int):
    """Return one page of transaction evidence."""
    pages = {
      1: ([
        {'hash': 'ABC', 'height': '100', 'tx_result': {'events': []}, 'tx': '', 'index': 0},
        {'hash': 'SEEN', 'height': '101', 'tx_result': {'events': []}, 'tx': '', 'index': 1},
      ], 2),
      2: ([
        {'hash': 'DEF', 'height': '102', 'tx_result': {'events': []}, 'tx': '', 'index': 0},
      ], None),
    }
    return pages[state]

class FakeSearchComet(FakeComet):
  """Fake Comet client with paged transaction search."""
  queries: list[tuple[str, int | None, str | None, bool | None]]

  def __init__(self):
    self.queries = []

  def tx_search_paged(
    self,
    query: str,
    *,
    per_page: int | None = None,
    order_by: str | None = None,
    validate: bool | None = None,
  ):
    """Return fake transaction search pages."""
    self.queries.append((query, per_page, order_by, validate))
    return FakePaging()

class FakeChain:
  """Fake chain client carrying Comet helpers."""

  comet: FakeComet = FakeComet()

class FakeClient:
  """Fake dYdX client carrying chain helpers."""

  chain: FakeChain = FakeChain()

def reporting() -> Reporting:
  """Create a reporting adapter with fake transports."""
  return Reporting(address=ADDRESS, client=FakeClient()) # type: ignore

class FakeBank:
  """Fake chain bank module for snapshot tests."""

  async def denom_metadata(self, denom: str):
    """Return display metadata for test denoms."""
    return bank_proto.QueryDenomMetadataResponse(
      metadata=bank_proto.Metadata(
        base=denom,
        display='dydx' if denom == 'adydx' else 'usdc',
        symbol='DYDX' if denom == 'adydx' else 'USDC',
        denom_units=[
          bank_proto.DenomUnit(denom=denom),
          bank_proto.DenomUnit(denom='dydx' if denom == 'adydx' else 'usdc', exponent=18 if denom == 'adydx' else 6),
        ],
      ),
    )

  async def all_balances_paged(self, address: str):
    """Return liquid wallet balances."""
    return [
      coin_proto.Coin(denom='adydx', amount='1000000000000000000'),
      coin_proto.Coin(denom=DYDX_MAINNET_USDC_DENOM, amount='1250000'),
    ]

class FakeStaking:
  """Fake chain staking module for snapshot tests."""

  async def delegator_delegations_paged(self, address: str):
    """Return staked DYDX balances."""
    return [
      staking_proto.DelegationResponse(
        balance=coin_proto.Coin(denom='adydx', amount='2000000000000000000'),
      ),
    ]

class FakeDistribution:
  """Fake chain distribution module for snapshot tests."""

  async def delegation_total_rewards(self, address: str):
    """Return unclaimed staking rewards."""
    return distribution_proto.QueryDelegationTotalRewardsResponse(
      total=[coin_proto.DecCoin(denom='adydx', amount='3000000000000000000')],
    )

class FakeSnapshotChain(FakeChain):
  """Fake chain modules needed by complete snapshot balances."""
  bank: FakeBank = FakeBank()
  staking: FakeStaking = FakeStaking()
  distribution: FakeDistribution = FakeDistribution()

class FakeSnapshotClient:
  """Fake client carrying full snapshot chain helpers."""
  chain: FakeSnapshotChain = FakeSnapshotChain()

class FakeSearchChain:
  """Fake chain client carrying searchable Comet helpers."""
  comet: FakeSearchComet

  def __init__(self):
    self.comet = FakeSearchComet()

class FakeSearchClient:
  """Fake dYdX client carrying searchable chain helpers."""
  chain: FakeSearchChain

  def __init__(self):
    self.chain = FakeSearchChain()

class StreamingReporting(Reporting):
  """Reporting adapter with controlled source completion order."""

  async def fetch_comet_txs(self, query: str, *, per_page: int = 100) -> list[TxResponse]:
    """Return empty node evidence for streaming orchestration tests."""
    return []

  async def subaccounts(self) -> list[Subaccount]:
    """Return one delayed subaccount."""
    await asyncio.sleep(0.03)
    return [{
      'address': ADDRESS,
      'subaccountNumber': 0,
      'equity': Decimal(0),
      'freeCollateral': Decimal(0),
      'openPerpetualPositions': {},
      'assetPositions': {},
      'marginEnabled': False,
      'updatedAtHeight': '0',
      'latestProcessedBlockHeight': '0',
    }]

  async def subaccount_records(
    self,
    subaccount: int,
    *,
    start: datetime | None,
    end: datetime | None,
    include_fills: bool,
    include_transfers: bool,
  ) -> tuple[list[Record], set[str]]:
    """Return delayed indexer records."""
    await asyncio.sleep(0.03)
    return ([Record(
      observations=[UnknownObservation(id='indexer', reason='test')],
      provenance={'source': 'api', 'service': 'dydx', 'endpoint': 'indexer'},
    )], set())

  async def bigquery_funding(self, *, start: datetime | None, end: datetime | None) -> list[Record]:
    """Return fast funding records."""
    await asyncio.sleep(0.01)
    return [Record(
      observations=[UnknownObservation(id='funding', reason='test')],
      provenance={'source': 'api', 'service': 'dydx', 'endpoint': 'funding'},
    )]

  async def chain_fees(
    self,
    txs: list[TxResponse],
    *,
    start: datetime | None,
    end: datetime | None,
  ) -> list[Record]:
    """Return delayed fee records."""
    await asyncio.sleep(0.05)
    return [Record(
      observations=[UnknownObservation(id='fees', reason='test')],
      provenance={'source': 'api', 'service': 'dydx', 'endpoint': 'fees'},
    )]

  async def bigquery_staking_transfers(self, *, start: datetime | None, end: datetime | None) -> list[Record]:
    """Return delayed staking records."""
    await asyncio.sleep(0.04)
    return [Record(
      observations=[UnknownObservation(id='staking', reason='test')],
      provenance={'source': 'api', 'service': 'dydx', 'endpoint': 'staking'},
    )]

  async def bigquery_native_wallet_transfers(self, *, start: datetime | None, end: datetime | None) -> list[Record]:
    """Return delayed native wallet records."""
    await asyncio.sleep(0.02)
    return [Record(
      observations=[UnknownObservation(id='native', reason='test')],
      provenance={'source': 'api', 'service': 'dydx', 'endpoint': 'native'},
    )]

  async def bigquery_trading_rewards(self, *, start: datetime | None, end: datetime | None) -> list[Record]:
    """Return no trading rewards for streaming orchestration tests."""
    return []

  async def chain_megavault_transfers(
    self,
    txs: list[TxResponse],
    *,
    start: datetime | None,
    end: datetime | None,
  ) -> list[Record]:
    """Return no Megavault records."""
    return []

  async def chain_ibc_transfers(
    self,
    txs: list[TxResponse],
    *,
    start: datetime | None,
    end: datetime | None,
  ) -> list[Record]:
    """Return no IBC records."""
    return []

def test_parse_fill() -> None:
  """Convert a dYdX indexer fill into an SDK trade observation."""
  record = reporting().parse_fill({
    'id': 'fill-1',
    'side': 'BUY',
    'liquidity': 'MAKER',
    'type': 'LIMIT',
    'market': 'BTC-USD',
    'marketType': 'PERPETUAL',
    'price': Decimal('50000'),
    'size': Decimal('0.01'),
    'fee': Decimal('0.02'),
    'affiliateRevShare': Decimal('0'),
    'createdAt': NOW,
    'createdAtHeight': '10',
    'subaccountNumber': 0,
    'orderId': 'order-1',
    'positionSizeBefore': Decimal('0'),
    'entryPriceBefore': Decimal('0'),
  })

  trade = record.observations[0]
  assert isinstance(trade, FutureTrade)
  assert trade.instrument == 'BTC-USD'
  assert trade.base == 'BTC'
  assert trade.quote == 'USD'
  assert trade.settle == 'USDC'
  assert not hasattr(trade, 'side')
  assert trade.size == Decimal('0.01')
  assert trade.realized_pnl == Decimal('0')
  assert trade.subaccount == 0
  assert trade.fee is not None
  assert trade.fee.asset == 'USDC'
  assert trade.fee.amount == Decimal('0.02')

def fill_trade(
  *,
  side: Literal['BUY', 'SELL'] = 'SELL',
  price: Decimal = Decimal('51000'),
  size: Decimal = Decimal('0.01'),
  position_size_before: Decimal | None = None,
  entry_price_before: Decimal | None = None,
) -> FutureTrade:
  """Parse one test fill and return its future trade observation."""
  fill: Fill = {
    'id': 'fill-1',
    'side': side,
    'liquidity': 'MAKER',
    'type': 'LIMIT',
    'market': 'BTC-USD',
    'marketType': 'PERPETUAL',
    'price': price,
    'size': size,
    'fee': Decimal('0.02'),
    'affiliateRevShare': Decimal('0'),
    'createdAt': NOW,
    'createdAtHeight': '10',
    'subaccountNumber': 0,
  }
  if position_size_before is not None:
    fill['positionSizeBefore'] = position_size_before
  if entry_price_before is not None:
    fill['entryPriceBefore'] = entry_price_before
  trade = reporting().parse_fill(fill).observations[0]
  assert isinstance(trade, FutureTrade)
  return trade

def test_parse_fill_realized_pnl_for_long_close() -> None:
  """Compute realized PnL when a fill reduces a long position."""
  trade = fill_trade(
    position_size_before=Decimal('0.05'),
    entry_price_before=Decimal('50000'),
  )

  assert trade.realized_pnl == Decimal('10.00')

def test_parse_fill_realized_pnl_for_short_close() -> None:
  """Compute realized PnL when a fill reduces a short position."""
  trade = fill_trade(
    side='BUY',
    price=Decimal('49000'),
    position_size_before=Decimal('-0.05'),
    entry_price_before=Decimal('50000'),
  )

  assert trade.realized_pnl == Decimal('10.00')

def test_parse_fill_realized_pnl_for_flip_only_counts_closed_size() -> None:
  """Compute realized PnL only on the closed portion of a flip fill."""
  trade = fill_trade(
    size=Decimal('0.08'),
    position_size_before=Decimal('0.05'),
    entry_price_before=Decimal('50000'),
  )

  assert trade.realized_pnl == Decimal('50.00')

def test_parse_fill_realized_pnl_missing_context_is_unknown() -> None:
  """Leave realized PnL unknown when dYdX omits prior position context."""
  trade = fill_trade()

  assert trade.realized_pnl is None

def test_parse_fills_reconstructs_realized_pnl_from_stream() -> None:
  """Reconstruct fill-level realized PnL when dYdX omits position context."""
  fills: list[Fill] = [
    {
      'id': 'open',
      'side': 'BUY',
      'liquidity': 'MAKER',
      'type': 'LIMIT',
      'market': 'BTC-USD',
      'marketType': 'PERPETUAL',
      'price': Decimal('50000'),
      'size': Decimal('0.05'),
      'fee': Decimal('0.01'),
      'affiliateRevShare': Decimal('0'),
      'createdAt': NOW,
      'createdAtHeight': '10',
      'subaccountNumber': 0,
    },
    {
      'id': 'close',
      'side': 'SELL',
      'liquidity': 'MAKER',
      'type': 'LIMIT',
      'market': 'BTC-USD',
      'marketType': 'PERPETUAL',
      'price': Decimal('51000'),
      'size': Decimal('0.02'),
      'fee': Decimal('0.01'),
      'affiliateRevShare': Decimal('0'),
      'createdAt': NOW,
      'createdAtHeight': '11',
      'subaccountNumber': 0,
    },
  ]

  records = reporting().parse_fills(fills, start=None, end=None)
  first = records[0].observations[0]
  second = records[1].observations[0]

  assert isinstance(first, FutureTrade)
  assert isinstance(second, FutureTrade)
  assert first.realized_pnl == Decimal('0')
  assert second.realized_pnl == Decimal('20.00')

@pytest.mark.asyncio
async def test_snapshot_balances_include_wallet_staking_and_collateral() -> None:
  """Build complete dYdX snapshot balances from subaccounts and chain state."""
  report = Reporting(address=ADDRESS, client=FakeSnapshotClient()) # type: ignore
  balances = await report.snapshot_balances(
    Decimal('47.185969'),
    {'BTC-USD': Decimal('0.01')},
    {'BTC-USD': Decimal('50000')},
  )

  assert balances['USDC'].qty == Decimal('48.435969')
  assert balances['DYDX'].qty == Decimal('6')
  assert 'DYDX:staked' not in balances
  assert 'DYDX:rewards' not in balances
  assert balances['BTC-USD'].kind == 'future'

@pytest.mark.asyncio
async def test_history_yields_completed_sources_without_final_aggregation() -> None:
  """Yield records as source tasks complete rather than after all tasks finish."""
  report = StreamingReporting(
    address=ADDRESS,
    client=FakeClient(), # type: ignore
    config={'sources': {
      'funding': 'bigquery',
      'staking': 'bigquery',
      'community_treasury_distributions': 'disabled',
      'megavault': 'disabled',
      'ibc_wallet_transfers': 'disabled',
      'wallet_transfers': 'disabled',
    }},
  )
  ids: list[str | None] = []

  async for record in report.history():
    ids.append(record.observations[0].id)

  assert ids[0] == 'funding'
  assert ids.index('funding') < ids.index('indexer')
  assert set(ids) == {'funding', 'indexer', 'staking', 'fees'}

def test_parse_coins_normalizes_native_denoms() -> None:
  """Parse dYdX native and USDC coin strings into reporting assets."""
  coins = parse_coins(f'201217357510726adydx,10534{DYDX_MAINNET_USDC_DENOM}')

  assert coins == [
    ('DYDX', Decimal('0.000201217357510726')),
    ('USDC', Decimal('0.010534')),
  ]

def test_parse_coins_normalizes_ibc_packet_usdc() -> None:
  """Parse IBC packet USDC denom into reporting USDC."""
  assert parse_coins('500000000uusdc') == [('USDC', Decimal('500'))]

def test_parse_fee_coin_rejects_multi_coin_fees() -> None:
  """Reject multi-denom tx fees because the SDK fee model is single-asset."""
  with pytest.raises(ValueError, match='Expected one dYdX fee coin'):
    parse_fee_coin(f'1adydx,2{DYDX_MAINNET_USDC_DENOM}')

def test_parse_settled_funding_event() -> None:
  """Convert a Comet settled funding event into an SDK funding observation."""
  record = reporting().parse_settled_funding_event({
    'type': 'settled_funding',
    'attributes': [
      {'key': 'subaccount', 'value': ADDRESS, 'index': True},
      {'key': 'subaccount_number', 'value': '0', 'index': True},
      {'key': 'perpetual_id', 'value': '0', 'index': True},
      {'key': 'funding_paid_quote_quantums', 'value': '500000', 'index': True},
    ],
  }, tx={
    'hash': 'ABC',
    'height': '100',
    'tx_result': {'events': []},
    'tx': '',
    'index': 0,
  }, time=NOW, event_index=3)

  assert record is not None
  funding = record.observations[0]
  assert isinstance(funding, Funding)
  assert funding.asset == 'USDC'
  assert funding.amount == Decimal('-0.5')
  assert funding.id == 'ABC:3'

def test_parse_settled_funding_event_ignores_other_accounts() -> None:
  """Ignore settled funding events for other account owners."""
  record = reporting().parse_settled_funding_event({
    'type': 'settled_funding',
    'attributes': [
      {'key': 'subaccount', 'value': 'dydx1other', 'index': True},
      {'key': 'subaccount_number', 'value': '0', 'index': True},
      {'key': 'perpetual_id', 'value': '0', 'index': True},
      {'key': 'funding_paid_quote_quantums', 'value': '500000', 'index': True},
    ],
  }, tx={
    'hash': 'ABC',
    'height': '100',
    'tx_result': {'events': []},
    'tx': '',
    'index': 0,
  }, time=NOW, event_index=3)

  assert record is None

def test_parse_bigquery_funding() -> None:
  """Convert a Numia settled funding row into an SDK funding observation."""
  record = reporting().parse_bigquery_funding({
    'block_timestamp': NOW,
    'tx_hash': 'ABC',
    'message_index': 0,
    'action_index': 2,
    'funding_paid_quote_quantums': Decimal('-250000'),
    'subaccount_number': 128,
  })

  funding = record.observations[0]
  assert isinstance(funding, Funding)
  assert funding.id == 'ABC:0:2'
  assert funding.asset == 'USDC'
  assert funding.settle == 'USDC'
  assert funding.amount == Decimal('0.25')
  assert funding.subaccount == 128

def test_parse_subaccount_transfer() -> None:
  """Convert dYdX subaccount transfers into internal transfers."""
  record = reporting().parse_transfer({
    'id': 'transfer-1',
    'sender': {'address': ADDRESS},
    'recipient': {'address': ADDRESS, 'subaccountNumber': 0},
    'size': Decimal('12.5'),
    'createdAt': NOW,
    'createdAtHeight': '10',
    'symbol': 'USDC',
    'type': 'DEPOSIT',
    'transactionHash': 'ABC',
  }, subaccount=0)

  assert record is not None
  transfer = record.observations[0]
  assert isinstance(transfer, InternalTransfer)
  assert transfer.asset == 'USDC'
  assert transfer.amount == Decimal('12.5')
  assert transfer.src_account == ADDRESS
  assert transfer.dst_account == f'{ADDRESS}:0'

def test_parse_external_subaccount_transfer() -> None:
  """Convert indexer subaccount credits into internal transfers."""
  record = reporting().parse_transfer({
    'id': 'transfer-2',
    'sender': {'address': 'dydx1external', 'subaccountNumber': 0},
    'recipient': {'address': ADDRESS, 'subaccountNumber': 128},
    'size': Decimal('25.343388'),
    'createdAt': NOW,
    'createdAtHeight': '10',
    'symbol': 'USDC',
    'type': 'TRANSFER_IN',
    'transactionHash': 'ABC',
  }, subaccount=128)

  assert record is not None
  transfer = record.observations[0]
  assert isinstance(transfer, InternalTransfer)
  assert transfer.asset == 'USDC'
  assert transfer.amount == Decimal('25.343388')
  assert transfer.src_account == 'dydx1external:0'
  assert transfer.dst_account == f'{ADDRESS}:128'

def test_parse_node_subaccount_deposit_event() -> None:
  """Convert a node subaccount deposit event into an internal transfer."""
  record = reporting().parse_subaccount_transfer_event({
    'type': 'deposit_to_subaccount',
    'attributes': [
      {'key': 'sender', 'value': ADDRESS, 'index': True},
      {'key': 'recipient', 'value': ADDRESS, 'index': True},
      {'key': 'recipient_number', 'value': '7', 'index': True},
      {'key': 'asset_id', 'value': '0', 'index': True},
      {'key': 'quantums', 'value': '12345678', 'index': True},
    ],
  }, tx={
    'hash': 'ABC',
    'height': '100',
    'tx_result': {'events': []},
    'tx': '',
    'index': 0,
  }, time=NOW, event_index=11)

  assert record is not None
  transfer = record.observations[0]
  assert isinstance(transfer, InternalTransfer)
  assert transfer.id == 'ABC:deposit_to_subaccount:11'
  assert transfer.asset == 'USDC'
  assert transfer.amount == Decimal('12.345678')
  assert transfer.src_account == f'dydx:{ADDRESS}:wallet'
  assert transfer.dst_account == f'dydx:{ADDRESS}:7'

def test_parse_node_subaccount_withdraw_event() -> None:
  """Convert a node subaccount withdrawal event into an internal transfer."""
  record = reporting().parse_subaccount_transfer_event({
    'type': 'withdraw_from_subaccount',
    'attributes': [
      {'key': 'sender', 'value': ADDRESS, 'index': True},
      {'key': 'sender_number', 'value': '7', 'index': True},
      {'key': 'recipient', 'value': ADDRESS, 'index': True},
      {'key': 'asset_id', 'value': '0', 'index': True},
      {'key': 'quantums', 'value': '87654321', 'index': True},
    ],
  }, tx={
    'hash': 'ABC',
    'height': '100',
    'tx_result': {'events': []},
    'tx': '',
    'index': 0,
  }, time=NOW, event_index=12)

  assert record is not None
  transfer = record.observations[0]
  assert isinstance(transfer, InternalTransfer)
  assert transfer.id == 'ABC:withdraw_from_subaccount:12'
  assert transfer.asset == 'USDC'
  assert transfer.amount == Decimal('87.654321')
  assert transfer.src_account == f'dydx:{ADDRESS}:7'
  assert transfer.dst_account == f'dydx:{ADDRESS}:wallet'

def test_parse_node_megavault_deposit_event() -> None:
  """Convert a node Megavault deposit event into a wallet transfer."""
  record = reporting().parse_megavault_event({
    'type': 'deposit_to_megavault',
    'attributes': [
      {'key': 'depositor', 'value': ADDRESS, 'index': True},
      {'key': 'quote_quantums', 'value': '10000000', 'index': True},
    ],
  }, tx={
    'hash': 'ABC',
    'height': '100',
    'tx_result': {'events': []},
    'tx': '',
    'index': 0,
  }, time=NOW, event_index=13)

  assert record is not None
  transfer = record.observations[0]
  assert isinstance(transfer, Transfer)
  assert transfer.id == 'ABC:deposit_to_megavault:13'
  assert transfer.asset == 'USDC'
  assert transfer.amount == Decimal('-10')
  assert transfer.src_account == f'dydx:{ADDRESS}:0'
  assert transfer.dst_account == f'dydx:{ADDRESS}:megavault'

def test_parse_node_megavault_withdraw_event() -> None:
  """Convert a node Megavault withdrawal event into a wallet transfer."""
  record = reporting().parse_megavault_event({
    'type': 'withdraw_from_megavault',
    'attributes': [
      {'key': 'withdrawer', 'value': ADDRESS, 'index': True},
      {'key': 'redeemed_quote_quantums', 'value': '9998721', 'index': True},
    ],
  }, tx={
    'hash': 'ABC',
    'height': '100',
    'tx_result': {'events': []},
    'tx': '',
    'index': 0,
  }, time=NOW, event_index=14)

  assert record is not None
  transfer = record.observations[0]
  assert isinstance(transfer, Transfer)
  assert transfer.id == 'ABC:withdraw_from_megavault:14'
  assert transfer.asset == 'USDC'
  assert transfer.amount == Decimal('9.998721')
  assert transfer.src_account == f'dydx:{ADDRESS}:megavault'
  assert transfer.dst_account == f'dydx:{ADDRESS}:0'

def test_parse_node_ibc_outbound_event() -> None:
  """Convert a node outbound IBC transfer event into a wallet transfer."""
  record = reporting().parse_ibc_transfer_event({
    'type': 'ibc_transfer',
    'attributes': [
      {'key': 'sender', 'value': ADDRESS, 'index': True},
      {'key': 'receiver', 'value': 'osmo1receiver', 'index': True},
      {'key': 'denom', 'value': DYDX_MAINNET_USDC_DENOM, 'index': True},
      {'key': 'amount', 'value': '42000000', 'index': True},
    ],
  }, tx={
    'hash': 'ABC',
    'height': '100',
    'tx_result': {'events': []},
    'tx': '',
    'index': 0,
  }, time=NOW, event_index=15)

  assert record is not None
  transfer = record.observations[0]
  assert isinstance(transfer, Transfer)
  assert transfer.id == 'ABC:ibc_transfer:15'
  assert transfer.asset == 'USDC'
  assert transfer.amount == Decimal('-42')
  assert transfer.src_account == ADDRESS
  assert transfer.dst_account == 'osmo1receiver'

def test_parse_node_create_transfer_event() -> None:
  """Convert a node create_transfer event into a subaccount transfer."""
  record = reporting().parse_subaccount_transfer_event({
    'type': 'create_transfer',
    'attributes': [
      {'key': 'sender', 'value': ADDRESS, 'index': True},
      {'key': 'sender_number', 'value': '0', 'index': True},
      {'key': 'recipient', 'value': ADDRESS, 'index': True},
      {'key': 'recipient_number', 'value': '128', 'index': True},
      {'key': 'asset_id', 'value': '0', 'index': True},
      {'key': 'quantums', 'value': '208725000', 'index': True},
    ],
  }, tx={
    'hash': 'ABC',
    'height': '100',
    'tx_result': {'events': []},
    'tx': '',
    'index': 0,
  }, time=NOW, event_index=12)

  assert record is not None
  transfer = record.observations[0]
  assert isinstance(transfer, InternalTransfer)
  assert transfer.id == 'ABC:create_transfer:12'
  assert transfer.asset == 'USDC'
  assert transfer.amount == Decimal('208.725')
  assert transfer.src_account == f'dydx:{ADDRESS}:0'
  assert transfer.dst_account == f'dydx:{ADDRESS}:128'

def test_parse_node_external_create_transfer_event() -> None:
  """Convert external node create_transfer credits into internal transfers."""
  record = reporting().parse_subaccount_transfer_event({
    'type': 'create_transfer',
    'attributes': [
      {'key': 'sender', 'value': 'dydx1external', 'index': True},
      {'key': 'sender_number', 'value': '0', 'index': True},
      {'key': 'recipient', 'value': ADDRESS, 'index': True},
      {'key': 'recipient_number', 'value': '128', 'index': True},
      {'key': 'asset_id', 'value': '0', 'index': True},
      {'key': 'quantums', 'value': '25343388', 'index': True},
    ],
  }, tx={
    'hash': 'ABC',
    'height': '100',
    'tx_result': {'events': []},
    'tx': '',
    'index': 0,
  }, time=NOW, event_index=13)

  assert record is not None
  transfer = record.observations[0]
  assert isinstance(transfer, InternalTransfer)
  assert transfer.id == 'ABC:create_transfer:13'
  assert transfer.asset == 'USDC'
  assert transfer.amount == Decimal('25.343388')
  assert transfer.src_account == 'dydx:dydx1external:0'
  assert transfer.dst_account == f'dydx:{ADDRESS}:128'

def test_parse_node_ibc_inbound_event() -> None:
  """Convert a successful node inbound IBC packet event into a wallet transfer."""
  record = reporting().parse_ibc_transfer_event({
    'type': 'fungible_token_packet',
    'attributes': [
      {'key': 'sender', 'value': 'osmo1sender', 'index': True},
      {'key': 'receiver', 'value': ADDRESS, 'index': True},
      {'key': 'denom', 'value': DYDX_MAINNET_USDC_DENOM, 'index': True},
      {'key': 'amount', 'value': '21000000', 'index': True},
      {'key': 'success', 'value': 'true', 'index': True},
    ],
  }, tx={
    'hash': 'ABC',
    'height': '100',
    'tx_result': {'events': []},
    'tx': '',
    'index': 0,
  }, time=NOW, event_index=16)

  assert record is not None
  transfer = record.observations[0]
  assert isinstance(transfer, Transfer)
  assert transfer.id == 'ABC:fungible_token_packet:16'
  assert transfer.asset == 'USDC'
  assert transfer.amount == Decimal('21')
  assert transfer.src_account == 'osmo1sender'
  assert transfer.dst_account == ADDRESS

@pytest.mark.asyncio
async def test_parse_chain_fee_tx() -> None:
  """Represent wallet-paid chain fees as crypto transaction metadata."""
  record = await reporting().parse_chain_fee_tx({
    'hash': 'ABC',
    'height': '100',
    'tx_result': {'events': [{
      'type': 'tx',
      'attributes': [
        {'key': 'fee', 'value': f'3577{DYDX_MAINNET_USDC_DENOM}', 'index': True},
        {'key': 'fee_payer', 'value': ADDRESS, 'index': True},
      ],
    }]},
    'tx': '',
    'index': 0,
  }, start=None, end=None)

  assert record is not None
  transaction = record.observations[0]
  assert isinstance(transaction, CryptoTransaction)
  assert transaction.id == 'ABC'
  assert transaction.tx_id == 'ABC'
  assert transaction.fee is not None
  assert transaction.fee.asset == 'USDC'
  assert transaction.fee.amount == Decimal('0.003577')

@pytest.mark.asyncio
async def test_parse_chain_fee_tx_normalizes_dydx_fee() -> None:
  """Normalize native dYdX chain fees into DYDX units."""
  record = await reporting().parse_chain_fee_tx({
    'hash': 'ABC',
    'height': '100',
    'tx_result': {'events': [{
      'type': 'tx',
      'attributes': [
        {'key': 'fee', 'value': '4982425000000000adydx', 'index': True},
        {'key': 'fee_payer', 'value': ADDRESS, 'index': True},
      ],
    }]},
    'tx': '',
    'index': 0,
  }, start=None, end=None)

  assert record is not None
  transaction = record.observations[0]
  assert isinstance(transaction, CryptoTransaction)
  assert transaction.fee is not None
  assert transaction.fee.asset == 'DYDX'
  assert transaction.fee.amount == Decimal('0.004982425')

def test_parse_staking_delegate_event() -> None:
  """Represent dYdX delegation as an internal transfer into staking."""
  record = reporting().parse_staking_event({
    'type': 'delegate',
    'attributes': [
      {'key': 'validator', 'value': 'dydxvaloper1abc', 'index': True},
      {'key': 'delegator', 'value': ADDRESS, 'index': True},
      {'key': 'amount', 'value': '152669867730366000000adydx', 'index': True},
    ],
  }, tx={
    'hash': 'ABC',
    'height': '100',
    'tx_result': {'events': []},
    'tx': '',
    'index': 0,
  }, time=NOW, event_index=9)

  assert record is not None
  transfer = record.observations[0]
  assert isinstance(transfer, InternalTransfer)
  assert transfer.id == 'ABC:delegate:9'
  assert transfer.asset == 'DYDX'
  assert transfer.amount == Decimal('152.669867730366')
  assert transfer.src_account == f'dydx:{ADDRESS}:wallet'
  assert transfer.dst_account == f'dydx:{ADDRESS}:staking:dydxvaloper1abc'

def test_parse_staking_unbond_event() -> None:
  """Represent dYdX unbonding as an internal transfer out of staking."""
  record = reporting().parse_staking_event({
    'type': 'unbond',
    'attributes': [
      {'key': 'validator', 'value': 'dydxvaloper1abc', 'index': True},
      {'key': 'delegator', 'value': ADDRESS, 'index': True},
      {'key': 'amount', 'value': '152669000000000000000adydx', 'index': True},
    ],
  }, tx={
    'hash': 'ABC',
    'height': '100',
    'tx_result': {'events': []},
    'tx': '',
    'index': 0,
  }, time=NOW, event_index=10)

  assert record is not None
  transfer = record.observations[0]
  assert isinstance(transfer, InternalTransfer)
  assert transfer.id == 'ABC:unbond:10'
  assert transfer.asset == 'DYDX'
  assert transfer.amount == Decimal('152.669')
  assert transfer.src_account == f'dydx:{ADDRESS}:staking:dydxvaloper1abc'
  assert transfer.dst_account == f'dydx:{ADDRESS}:wallet'

def test_parse_bigquery_delegate_transfer() -> None:
  """Represent Numia delegate rows as internal staking transfers."""
  record = reporting().parse_bigquery_staking_transfer({
    'block_timestamp': NOW,
    'tx_hash': 'ABC',
    'message_index': 0,
    'action_index': 1,
    'validator': 'dydxvaloper1abc',
    'token_amount': Decimal('152669867730366000000'),
    'token_denom': 'adydx',
  }, kind='delegate')

  transfer = record.observations[0]
  assert isinstance(transfer, InternalTransfer)
  assert transfer.id == 'ABC:delegate:0:1'
  assert transfer.asset == 'DYDX'
  assert transfer.amount == Decimal('152.669867730366')
  assert transfer.src_account == f'dydx:{ADDRESS}:wallet'
  assert transfer.dst_account == f'dydx:{ADDRESS}:staking:dydxvaloper1abc'

def test_parse_bigquery_undelegate_transfer_uses_completion_time() -> None:
  """Represent Numia undelegate rows as completed internal staking transfers."""
  record = reporting().parse_bigquery_staking_transfer({
    'block_timestamp': datetime(2026, 4, 22, 14, 53, tzinfo=timezone.utc),
    'completion_time': '2026-05-13T14:53:18Z',
    'tx_hash': 'ABC',
    'message_index': 0,
    'action_index': 1,
    'validator': 'dydxvaloper1abc',
    'token_amount': Decimal('152669000000000000000'),
    'token_denom': 'adydx',
  }, kind='undelegate')

  transfer = record.observations[0]
  assert isinstance(transfer, InternalTransfer)
  assert transfer.time == datetime(2026, 5, 13, 14, 53, 18, tzinfo=timezone.utc)
  assert transfer.src_account == f'dydx:{ADDRESS}:staking:dydxvaloper1abc'
  assert transfer.dst_account == f'dydx:{ADDRESS}:wallet'

def test_parse_bigquery_staking_reward() -> None:
  """Represent Numia withdraw_rewards message events as yield observations."""
  record = reporting().parse_bigquery_staking_reward({
    'block_timestamp': NOW,
    'tx_hash': 'ABC',
    'event_index': 5,
    'event_attributes': {
      'amount': '201217357510726adydx,10534ibc/8E27BA2D5493AF5636760E354E46004562C46AB7EC0CC4C1CA14E9E20E2545B5',
      'delegator': ADDRESS,
      'validator': 'dydxvaloper1abc',
    },
  })

  assert record is not None
  assert len(record.observations) == 2
  first, second = record.observations
  assert isinstance(first, Yield)
  assert isinstance(second, Yield)
  assert first.id == 'ABC:withdraw_rewards:5:0'
  assert first.asset == 'DYDX'
  assert first.amount == Decimal('0.000201217357510726')
  assert second.asset == 'USDC'
  assert second.amount == Decimal('0.010534')

def test_parse_bigquery_trading_reward() -> None:
  """Represent Numia trading reward rows as yield observations."""
  record = reporting().parse_bigquery_trading_reward({
    'block_height': 56463881,
    'block_timestamp': NOW,
    'action_index': 6,
    'sender': 'dydx16wrau2x4tsg033xfrrdpae6kxfn9kyuerr5jjp',
    'recipient': ADDRESS,
    'token_amount': Decimal('3694541597371286'),
    'token_denom': 'adydx',
  })

  reward = record.observations[0]
  assert isinstance(reward, Yield)
  assert reward.id == '56463881:6'
  assert reward.asset == 'DYDX'
  assert reward.amount == Decimal('0.003694541597371286')

def test_parse_bigquery_native_wallet_transfer() -> None:
  """Represent raw EndBlock transfers as internal wallet movements."""
  record = reporting().parse_bigquery_native_wallet_transfer({
    'block_height': 54816914,
    'block_timestamp': NOW,
    'event_index': 12666,
    'event_type': 'transfer',
    'event_attributes': {
      'amount': '7000000000000000000adydx',
      'mode': 'EndBlock',
      'recipient': ADDRESS,
      'sender': 'dydx15ztc7xy42tn2ukkc0qjthkucw9ac63pgp70urn',
    },
  })

  assert record is not None
  transfer = record.observations[0]
  assert isinstance(transfer, InternalTransfer)
  assert transfer.id == '54816914:12666:0'
  assert transfer.asset == 'DYDX'
  assert transfer.amount == Decimal('7')
  assert transfer.src_account == 'dydx15ztc7xy42tn2ukkc0qjthkucw9ac63pgp70urn'
  assert transfer.dst_account == ADDRESS

def test_parse_bigquery_community_treasury_distribution() -> None:
  """Represent Community Treasury block-event transfers as yield observations."""
  record = reporting().parse_bigquery_community_treasury_distribution({
    'block_height': 54816914,
    'block_timestamp': NOW,
    'event_index': 12667,
    'event_type': 'transfer',
    'event_attributes': {
      'amount': f'2500000{DYDX_MAINNET_USDC_DENOM},7000000000000000000adydx',
      'mode': 'EndBlock',
      'recipient': ADDRESS,
      'sender': COMMUNITY_TREASURY_ADDRESS,
    },
  })

  assert record is not None
  usdc = record.observations[0]
  dydx = record.observations[1]
  assert isinstance(usdc, Yield)
  assert isinstance(dydx, Yield)
  assert usdc.id == '54816914:12667:community_treasury:0'
  assert usdc.asset == 'USDC'
  assert usdc.amount == Decimal('2.5')
  assert dydx.id == '54816914:12667:community_treasury:1'
  assert dydx.asset == 'DYDX'
  assert dydx.amount == Decimal('7')

def test_parse_bigquery_subaccount_transfer() -> None:
  """Represent Numia subaccount-to-subaccount rows as internal transfers."""
  record = reporting().parse_bigquery_subaccount_transfer({
    'block_timestamp': NOW,
    'tx_hash': 'ABC',
    'message_index': 1,
    'action_index': 2,
    'sender': ADDRESS,
    'sender_number': 3,
    'recipient': ADDRESS,
    'recipient_number': 7,
    'quantums': Decimal('12500000'),
  }, table='dydx_transfer')

  assert record is not None
  transfer = record.observations[0]
  assert isinstance(transfer, InternalTransfer)
  assert transfer.id == 'ABC:dydx_transfer:1:2'
  assert transfer.asset == 'USDC'
  assert transfer.amount == Decimal('12.5')
  assert transfer.src_account == f'dydx:{ADDRESS}:3'
  assert transfer.dst_account == f'dydx:{ADDRESS}:7'

def test_parse_bigquery_subaccount_transfer_preserves_zero_subaccount() -> None:
  """Preserve zero-valued Numia subaccount numbers in transfer rows."""
  record = reporting().parse_bigquery_subaccount_transfer({
    'block_timestamp': NOW,
    'tx_hash': 'ABC',
    'message_index': 1,
    'action_index': 2,
    'sender': ADDRESS,
    'sender_number': 0,
    'recipient': ADDRESS,
    'recipient_number': 7,
    'quantums': Decimal('12500000'),
  }, table='dydx_transfer')

  assert record is not None
  transfer = record.observations[0]
  assert isinstance(transfer, InternalTransfer)
  assert transfer.src_account == f'dydx:{ADDRESS}:0'

def test_parse_bigquery_external_subaccount_transfer() -> None:
  """Represent external Numia subaccount credits as internal transfers."""
  record = reporting().parse_bigquery_subaccount_transfer({
    'block_timestamp': NOW,
    'tx_hash': 'ABC',
    'message_index': 1,
    'action_index': 2,
    'sender': 'dydx1external',
    'sender_number': 0,
    'recipient': ADDRESS,
    'recipient_number': 128,
    'quantums': Decimal('25343388'),
  }, table='dydx_transfer')

  assert record is not None
  transfer = record.observations[0]
  assert isinstance(transfer, InternalTransfer)
  assert transfer.id == 'ABC:dydx_transfer:1:2'
  assert transfer.asset == 'USDC'
  assert transfer.amount == Decimal('25.343388')
  assert transfer.src_account == 'dydx:dydx1external:0'
  assert transfer.dst_account == f'dydx:{ADDRESS}:128'

def test_parse_bigquery_wallet_transfer() -> None:
  """Represent unmatched Numia wallet transfers as balance-changing transfers."""
  record = reporting().parse_bigquery_wallet_transfer({
    'block_timestamp': NOW,
    'tx_hash': 'ABC',
    'event_index': 42,
    'event_attributes': {
      'sender': 'dydx1module',
      'recipient': ADDRESS,
      'amount': '1234567ibc/8E27BA2D5493AF5636760E354E46004562C46AB7EC0CC4C1CA14E9E20E2545B5',
    },
  })

  assert record is not None
  transfer = record.observations[0]
  assert isinstance(transfer, Transfer)
  assert transfer.id == 'ABC:wallet_transfer:42:0'
  assert transfer.asset == 'USDC'
  assert transfer.amount == Decimal('1.234567')
  assert transfer.src_account == 'dydx1module'
  assert transfer.dst_account == ADDRESS

def test_parse_bigquery_megavault_deposit() -> None:
  """Represent Numia Megavault deposit events as wallet transfers."""
  record = reporting().parse_bigquery_megavault_transfer({
    'block_timestamp': NOW,
    'tx_hash': 'ABC',
    'message_index': 1,
    'event_index': 3,
    'event_type': 'deposit_to_megavault',
    'event_attributes': {
      'depositor': ADDRESS,
      'quote_quantums': '10000000',
    },
  })

  assert record is not None
  transfer = record.observations[0]
  assert isinstance(transfer, Transfer)
  assert transfer.id == 'ABC:deposit_to_megavault:3'
  assert transfer.asset == 'USDC'
  assert transfer.amount == Decimal('-10')
  assert transfer.src_account == f'dydx:{ADDRESS}:0'
  assert transfer.dst_account == f'dydx:{ADDRESS}:megavault'

def test_parse_bigquery_megavault_withdraw() -> None:
  """Represent Numia Megavault withdrawal events as wallet transfers."""
  record = reporting().parse_bigquery_megavault_transfer({
    'block_timestamp': NOW,
    'tx_hash': 'ABC',
    'message_index': 2,
    'event_index': 4,
    'event_type': 'withdraw_from_megavault',
    'event_attributes': {
      'withdrawer': ADDRESS,
      'redeemed_quote_quantums': '9998721',
    },
  })

  assert record is not None
  transfer = record.observations[0]
  assert isinstance(transfer, Transfer)
  assert transfer.id == 'ABC:withdraw_from_megavault:4'
  assert transfer.asset == 'USDC'
  assert transfer.amount == Decimal('9.998721')
  assert transfer.src_account == f'dydx:{ADDRESS}:megavault'
  assert transfer.dst_account == f'dydx:{ADDRESS}:0'

def test_parse_bigquery_ibc_outbound_transfer() -> None:
  """Represent Numia outbound IBC transfer events as wallet transfers."""
  record = reporting().parse_bigquery_ibc_wallet_transfer({
    'block_timestamp': NOW,
    'tx_hash': 'ABC',
    'message_index': 1,
    'event_index': 5,
    'event_type': 'ibc_transfer',
    'event_attributes': {
      'sender': ADDRESS,
      'receiver': 'osmo1receiver',
      'denom': DYDX_MAINNET_USDC_DENOM,
      'amount': '42000000',
    },
  })

  assert record is not None
  transfer = record.observations[0]
  assert isinstance(transfer, Transfer)
  assert transfer.id == 'ABC:ibc:5'
  assert transfer.asset == 'USDC'
  assert transfer.amount == Decimal('-42')
  assert transfer.src_account == ADDRESS
  assert transfer.dst_account == 'osmo1receiver'

def test_parse_bigquery_ibc_inbound_transfer() -> None:
  """Represent Numia inbound IBC receive events as wallet transfers."""
  record = reporting().parse_bigquery_ibc_wallet_transfer({
    'block_timestamp': NOW,
    'tx_hash': 'ABC',
    'message_index': 2,
    'event_index': 6,
    'event_type': 'fungible_token_packet',
    'event_attributes': {
      'sender': 'osmo1sender',
      'receiver': ADDRESS,
      'denom': DYDX_MAINNET_USDC_DENOM,
      'amount': '21000000',
      'success': 'true',
    },
  })

  assert record is not None
  transfer = record.observations[0]
  assert isinstance(transfer, Transfer)
  assert transfer.id == 'ABC:ibc:6'
  assert transfer.asset == 'USDC'
  assert transfer.amount == Decimal('21')
  assert transfer.src_account == 'osmo1sender'
  assert transfer.dst_account == ADDRESS

@pytest.mark.asyncio
async def test_parse_inbound_fallback_tx() -> None:
  """Represent unsupported inbound wallet credits as fallback chain evidence."""
  record = await reporting().parse_inbound_fallback_tx({
    'hash': 'ABC',
    'height': '100',
    'tx_result': {'events': [{
      'type': 'transfer',
      'attributes': [
        {'key': 'sender', 'value': 'dydx1module', 'index': True},
        {'key': 'recipient', 'value': ADDRESS, 'index': True},
        {'key': 'amount', 'value': f'150{DYDX_MAINNET_USDC_DENOM}', 'index': True},
      ],
    }]},
    'tx': '',
    'index': 0,
  }, covered_hashes=set(), include_fee=True, start=None, end=None)

  assert record is not None
  transaction = record.observations[0]
  unknown = record.observations[1]
  assert isinstance(transaction, CryptoTransaction)
  assert transaction.id == 'ABC'
  assert len(transaction.transfers) == 1
  assert transaction.transfers[0].asset == 'USDC'
  assert transaction.transfers[0].change == Decimal('0.000150')
  assert transaction.transfers[0].counterparty == 'dydx1module'
  assert isinstance(unknown, UnknownObservation)
  assert unknown.id == 'ABC:unknown'

@pytest.mark.asyncio
async def test_parse_inbound_fallback_tx_parses_multi_coin_transfers() -> None:
  """Represent each coin in a multi-denom Comet transfer amount."""
  record = await reporting().parse_inbound_fallback_tx({
    'hash': 'ABC',
    'height': '100',
    'tx_result': {'events': [{
      'type': 'transfer',
      'attributes': [
        {'key': 'sender', 'value': 'dydx1module', 'index': True},
        {'key': 'recipient', 'value': ADDRESS, 'index': True},
        {'key': 'amount', 'value': f'201217357510726adydx,10534{DYDX_MAINNET_USDC_DENOM}', 'index': True},
      ],
    }]},
    'tx': '',
    'index': 0,
  }, covered_hashes=set(), include_fee=True, start=None, end=None)

  assert record is not None
  transaction = record.observations[0]
  assert isinstance(transaction, CryptoTransaction)
  assert [(transfer.asset, transfer.change) for transfer in transaction.transfers] == [
    ('DYDX', Decimal('0.000201217357510726')),
    ('USDC', Decimal('0.010534')),
  ]

@pytest.mark.asyncio
async def test_inbound_fallback_skips_covered_hashes() -> None:
  """Avoid generic inbound fallback for hashes covered by indexer transfers."""
  record = await reporting().parse_inbound_fallback_tx({
    'hash': 'ABC',
    'height': '100',
    'tx_result': {'events': [{
      'type': 'transfer',
      'attributes': [
        {'key': 'sender', 'value': 'dydx1module', 'index': True},
        {'key': 'recipient', 'value': ADDRESS, 'index': True},
        {'key': 'amount', 'value': f'150{DYDX_MAINNET_USDC_DENOM}', 'index': True},
      ],
    }]},
    'tx': '',
    'index': 0,
  }, covered_hashes={'ABC'}, include_fee=True, start=None, end=None)

  assert record is None

@pytest.mark.asyncio
async def test_fetch_comet_txs_uses_paged_search() -> None:
  """Collect raw Comet transactions through tx_search_paged."""
  client = FakeSearchClient()
  report = Reporting(address=ADDRESS, client=client) # type: ignore
  txs = await report.fetch_comet_txs(f"tx.fee_payer='{ADDRESS}'", per_page=25)

  assert [tx.get('hash') for tx in txs] == ['ABC', 'SEEN', 'DEF']
  assert client.chain.comet.queries == [
    (f"tx.fee_payer='{ADDRESS}'", 25, 'desc', None),
  ]

def test_reporting_sdk_registers_dydx() -> None:
  """Expose dYdX through the generic reporting registry."""
  sdk = ReportSDK()
  assert 'dydx' in sdk.venues()
  assert isinstance(sdk.dydx(address=ADDRESS), Report)
  assert isinstance(sdk.venue('dydx', address=ADDRESS), Report)

def test_small_helpers() -> None:
  """Check dYdX reporting helper behavior."""
  assert in_window(NOW, start=None, end=None)
  assert account_label({'address': ADDRESS, 'subaccountNumber': 1}) == f'{ADDRESS}:1'
  assert event_attributes({
    'type': 'settled_funding',
    'attributes': [{'key': 'subaccount_number', 'value': '0', 'index': True}],
  }) == {'subaccount_number': '0'}
