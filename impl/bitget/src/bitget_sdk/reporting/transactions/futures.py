from typing_extensions import AsyncIterable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
import warnings

from sdk.core import Stream, ChunkedStream
from sdk.reporting.transactions import (
  Flow, SingleEvent,match_transactions,
  Transaction, FutureTrade, Fee
)

from bitget import Bitget
from bitget.futures.trade.fills import fill_direction

DEFAULT_TRANSACTION_TYPES: dict[str, Flow.Label] = {
  'close_long': 'settlement', # closing P/L
  'close_short': 'settlement', # closing P/L
  'burst_close_long': 'settlement', # closing P/L
  'burst_close_short': 'settlement', # closing P/L

  'contract_margin_settle_fee': 'funding',
  'contract_main_settle_fee': 'funding',

  'user_grants_issue': 'bonus',
  'bonus_issue': 'bonus',
  'bonus_recycle': 'bonus',

  'trans_to_strategy': 'strategy_deposit',
  'trans_from_strategy': 'strategy_withdrawal',
  'transfer_to_future_copytrade': 'strategy_deposit',
  'transfer_from_future_copytrade': 'strategy_withdrawal',
  
  'risk_captital_user_transfer': 'other',

  'trans_from_exchange': 'internal_transfer',
  'trans_to_exchange': 'internal_transfer',
}
DEFAULT_IGNORE_TYPES: set[str] = {
  'open_long', # 0-value postings
  'open_short', # 0-value postings
  'burst_open_long', # 0-value postings
  'burst_open_short', # 0-value postings
}

@dataclass
class FutureTransactions:
  client: Bitget
  transaction_types: dict[str, Flow.Label] = field(kw_only=True, default_factory=lambda: DEFAULT_TRANSACTION_TYPES)
  ignore_types: set[str] = field(kw_only=True, default_factory=lambda: DEFAULT_IGNORE_TYPES)
  unkwown_types_as_other: bool = field(kw_only=True, default=True)

  def transaction_type(self, type: str) -> Flow.Label | None:
    if type not in self.ignore_types:
      if type not in self.transaction_types:
        if self.unkwown_types_as_other:
          return 'other'
        else:
          raise ValueError(f"Unknown transaction type: {type}. Set `unkwown_types_as_other` to `True` to treat unknown types as `other`, or set `transactio_types`/`ignore_types`.")
      return self.transaction_types[type]

  @Stream.lift
  async def postings(self, start: datetime, end: datetime):
    async for chunk in self.client.common.tax.futures_transaction_records_paged(start=start, end=end):
      for tx in chunk:
        if (type := self.transaction_type(tx['futureTaxType'])) is not None:
          yield Flow(
            asset=tx['marginCoin'], change=tx['amount'],
            kind='currency', time=tx['ts'], details=tx,
            label=type,
          )
        if (fee := abs(tx['fee'])) > 0:
          yield Flow(
            asset=tx['marginCoin'], change=-fee,
            kind='currency', time=tx['ts'],
            details=tx, label='fee',
          )

  @Stream.lift
  async def trades(self, start: datetime, end: datetime):
    async for chunk in self.client.futures.trade.all_fills_paged(start=start, end=end):
      for fill in chunk:
        if len(fill['feeDetail']) > 1:
          warnings.warn(f"UNEXPECTED: Multiple fee details for fill {fill['tradeId']}: {fill['feeDetail']}")
        if not fill['feeDetail'] or (fee := abs(fill['feeDetail'][0]['totalFee'] or Decimal(0))) == 0:
          fee = None
        else:
          fee = Fee(amount=fee, asset=fill['feeDetail'][0]['feeCoin'])

        yield FutureTrade(
          id=fill['tradeId'],
          time=fill['cTime'],
          instrument=fill['symbol'],
          size=fill['baseVolume'],
          price=fill['price'],
          liquidity=fill['tradeScope'],
          side=fill_direction(fill),
          details=fill,
          fee=fee,
        )

  @ChunkedStream.lift
  async def __call__(self, start: datetime, end: datetime) -> AsyncIterable[list[Transaction]]:
    postings = await self.postings(start, end)
    trades = await self.trades(start, end)

    matched_txs, other_postings = match_transactions(postings, trades)
    yield matched_txs
    yield [Transaction.single(posting.details['id'], posting) for posting in other_postings]