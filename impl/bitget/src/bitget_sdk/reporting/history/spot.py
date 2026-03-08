from typing_extensions import AsyncIterable
from dataclasses import dataclass, field
from datetime import datetime

from trading_sdk.core import SDK
from trading_sdk.reporting.history import (
  Flow, SpotTrade, CryptoDeposit, CryptoWithdrawal, History
)
from bitget import Bitget
from bitget.spot.public.symbols import Symbol

from .util import TimezoneMixin

@dataclass(kw_only=True)
class SpotHistory(TimezoneMixin, History):
  client: Bitget
  symbols_cache: dict[str, Symbol] | None = field(kw_only=True, default=None)

  @property
  async def symbols(self) -> dict[str, Symbol]:
    if self.symbols_cache is None:
      self.symbols_cache = {s['symbol']: s for s in await self.client.spot.public.symbols()}
    return self.symbols_cache

  @SDK.method
  async def flows(self, start: datetime, end: datetime):
    async for chunk in self.client.common.tax.spot_transaction_records_paged(start=start, end=end):
      for tx in chunk:
        yield Flow(
          asset=tx['coin'], change=tx['amount'],
          time=self.add_tz(tx['ts']),
          raw=tx,
          event_tag=tx['spotTaxType'],
          source='bitget:spot_transaction_records',
        )
        if (fee := abs(tx['fee'])) > 0:
          yield Flow(
            asset=tx['coin'], change=-fee,
            time=self.add_tz(tx['ts']),
            raw=tx,
            event_tag='fee',
            source='bitget:spot_transaction_records',
          )

  @SDK.method
  async def trades(self, start: datetime, end: datetime):
    symbols = await self.symbols
    async for chunk in self.client.spot.trade.fills_paged(start=start, end=end):
      for fill in chunk:
        base = symbols[fill['symbol']]['baseCoin']
        quote = symbols[fill['symbol']]['quoteCoin']
        yield SpotTrade(
          id=fill['tradeId'],
          time=self.add_tz(fill['cTime']),
          base=base, quote=quote,
          qty=fill['size'], price=fill['priceAvg'],
          liquidity=fill['tradeScope'],
          side=fill['side'],
          fee=abs(fill['feeDetail']['totalFee']),
          fee_asset=fill['feeDetail']['feeCoin'],
          raw=fill,
          source='bitget:spot_fills',
        )

  @SDK.method
  async def deposits(self, start: datetime, end: datetime):
    async for chunk in self.client.spot.wallet.deposit_records_paged(start, end):
      for deposit in chunk:
        if deposit['dest'] != 'on_chain' or deposit['status'] != 'success':
          continue
        yield CryptoDeposit(
          id=deposit['tradeId'],
          time=self.add_tz(deposit['cTime']),
          asset=deposit['coin'],
          qty=deposit['size'],
          network=deposit['chain'],
          tx_hash=deposit['tradeId'],
          raw=deposit,
          source='bitget:spot_deposits',
        )
  
  @SDK.method
  async def withdrawals(self, start: datetime, end: datetime):
    async for chunk in self.client.spot.wallet.withdrawal_records_paged(start, end):
      for withdrawal in chunk:
        if withdrawal['dest'] != 'on_chain' or withdrawal['status'] != 'success':
          continue
        
        fee = abs(withdrawal['fee'])
        yield CryptoWithdrawal(
          id=withdrawal['tradeId'],
          time=self.add_tz(withdrawal['cTime']),
          asset=withdrawal['coin'],
          qty=withdrawal['size'],
          network=withdrawal['chain'],
          tx_hash=withdrawal['tradeId'],
          dst_address=withdrawal['toAddress'],
          fee=fee,
          fee_asset=withdrawal['coin'],
          raw=withdrawal,
          source='bitget:spot_withdrawals',
        )

  @SDK.method
  async def history(self, start: datetime, end: datetime) -> AsyncIterable[History.History]:
    flows = [f async for f in self.flows(start, end)]
    yield History.History(flows=flows)
    trades = [t async for t in self.trades(start, end)]
    yield History.History(events=trades)
    deposits = [d async for d in self.deposits(start, end)]
    yield History.History(events=deposits)
    withdrawals = [w async for w in self.withdrawals(start, end)]
    yield History.History(events=withdrawals)