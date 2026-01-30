from typing_extensions import AsyncIterable
from dataclasses import dataclass, field
from datetime import datetime

from sdk.core import Stream, ChunkedStream
from sdk.reporting.transactions import (
  Flow, match_transactions,
  Transaction, Trade, CryptoDeposit, CryptoWithdrawal, Fee
)
from bitget import Bitget
from bitget.spot.market.symbols import Symbol

DEFAULT_TRANSACTION_TYPES: dict[str, Flow.Label] = {
  'Buy': 'trade',
  'Sell': 'trade',
  'Deposit': 'crypto_deposit',
  'Withdrawal': 'crypto_withdrawal',
  'rebate_coupon_activity_user_in': 'bonus',
  'batch_interest_user_in': 'yield',
  'Interest': 'yield',
  '': 'other',
  'Rebate rewards': 'other',
  'Automatic deposit': 'strategy_withdrawal', # deposit from strategy, i.e. withdrawal from strategy
  'Automatic withdrawal': 'strategy_deposit', # withdrawal from account, i.e. deposit to strategy - they got it backwards
  'Crypto Voucher Distribution': 'bonus',

  'Transfer out': 'internal_transfer',
  'Transfer in': 'internal_transfer',
}

DEFAULT_IGNORE_TYPES: set[str] = {
  'financial_lock_out', # earn lock-in/-out
  'financial_unlock_in', # earn lock-in/-out
  'financial_user_out', # earn lock-in/-out
  'Redemption', # earn lock-in/-out
}

@dataclass
class SpotTransactions:
  client: Bitget
  transaction_types: dict[str, Flow.Label] = field(kw_only=True, default_factory=lambda: DEFAULT_TRANSACTION_TYPES)
  ignore_types: set[str] = field(kw_only=True, default_factory=lambda: DEFAULT_IGNORE_TYPES)
  unkwown_types_as_other: bool = field(kw_only=True, default=True)
  symbols: dict[str, Symbol] | None = field(kw_only=True, default=None)

  @property
  async def symbols_map(self) -> dict[str, Symbol]:
    if self.symbols is None:
      self.symbols = {s['symbol']: s for s in await self.client.spot.market.symbols()}
    return self.symbols

  def transaction_type(self, type: str) -> Flow.Label | None:
    if type not in self.ignore_types:
      if type not in self.transaction_types:
        if self.unkwown_types_as_other:
          return 'other'
        else:
          raise ValueError(f"Unknown transaction type: {type}. Set `unkwown_types_as_other` to `True` to treat unknown types as `other`, or set `transactio_types`/`ignore_types`.")
      return self.transaction_types[type]

  def fee_type(self, type: Flow.Label | None) -> Flow.Label:
    match type:
      case 'crypto_withdrawal' | 'fiat_withdrawal':
        return 'withdrawal_fee'
      case _:
        return 'fee'

  @Stream.lift
  async def flows(self, start: datetime, end: datetime):
    async for chunk in self.client.common.tax.spot_transaction_records_paged(start=start, end=end):
      for tx in chunk:
        if (type := self.transaction_type(tx['spotTaxType'])) is not None:
          yield Flow(
            asset=tx['coin'], change=tx['amount'],
            kind='currency', time=tx['ts'], details=tx,
            label=type,
          )
        if (fee := abs(tx['fee'])) > 0:
          yield Flow(
            asset=tx['coin'], change=-fee,
            kind='currency', time=tx['ts'],
            details=tx, label=self.fee_type(type),
          )

  @Stream.lift
  async def trades(self, start: datetime, end: datetime):
    symbols_map = await self.symbols_map
    async for chunk in self.client.spot.trade.fills_paged(start=start, end=end):
      for fill in chunk:
        base = symbols_map[fill['symbol']]['baseCoin']
        quote = symbols_map[fill['symbol']]['quoteCoin']
        fee = abs(fill['feeDetail']['totalFee'])
        fee = Fee(amount=fee, asset=fill['feeDetail']['feeCoin']) if fee > 0 else None
        yield Trade(
          id=fill['tradeId'],
          time=fill['cTime'],
          base=base, quote=quote,
          qty=fill['size'], price=fill['priceAvg'],
          liquidity=fill['tradeScope'],
          side=fill['side'],
          details=fill,
          fee=fee,
        )

  @Stream.lift
  async def deposits(self, start: datetime, end: datetime):
    async for chunk in self.client.spot.account.deposit_records_paged(start, end):
      for deposit in chunk:
        if deposit['dest'] != 'on_chain' or deposit['status'] != 'success':
          continue
        yield CryptoDeposit(
          id=deposit['tradeId'],
          time=deposit['cTime'],
          details=deposit,
          asset=deposit['coin'],
          qty=deposit['size'],
          network=deposit['chain'],
          tx_hash=deposit['tradeId'],
        )
  
  @Stream.lift
  async def withdrawals(self, start: datetime, end: datetime):
    async for chunk in self.client.spot.account.withdrawal_records_paged(start, end):
      for withdrawal in chunk:
        if withdrawal['dest'] != 'on_chain' or withdrawal['status'] != 'success':
          continue
        
        fee = abs(withdrawal['fee'])
        yield CryptoWithdrawal(
          id=withdrawal['tradeId'],
          time=withdrawal['cTime'],
          details=withdrawal,
          asset=withdrawal['coin'],
          qty=withdrawal['size'],
          network=withdrawal['chain'],
          tx_hash=withdrawal['tradeId'],
          address=withdrawal['toAddress'],
          fee=Fee(amount=fee, asset=withdrawal['coin']) if fee > 0 else None,
        )

  @ChunkedStream.lift
  async def __call__(self, start: datetime, end: datetime) -> AsyncIterable[list[Transaction]]:
    flows = await self.flows(start, end)
    trades = await self.trades(start, end)
    deposits = await self.deposits(start, end)
    withdrawals = await self.withdrawals(start, end)
    operations = list(trades) + list(deposits) + list(withdrawals)

    matched_txs, other_flows = match_transactions(flows, operations)
    yield matched_txs
    yield [Transaction.single(flow.details['id'], flow) for flow in other_flows]