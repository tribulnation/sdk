from typing_extensions import AsyncIterable
from dataclasses import dataclass, field
from datetime import datetime

from tribulnation.sdk.core import SDK
from tribulnation.sdk.reporting import (
  CryptoDeposit,
  CryptoWithdrawal,
  FeeLeg,
  Observation,
  Record,
  Trade,
  UnknownObservation,
)
from tribulnation.sdk.reporting import History as SdkHistory
from bitget import Bitget
from bitget.spot.public.symbols import Symbol

from .util import (
  TimezoneMixin,
  api_record,
  api_record_many,
  nonzero_fee,
  require_range,
  signed_size,
)

@dataclass(kw_only=True)
class SpotHistory(TimezoneMixin, SdkHistory):
  """Bitget spot account history."""
  client: Bitget
  symbols_cache: dict[str, Symbol] | None = field(kw_only=True, default=None)

  @property
  async def symbols(self) -> dict[str, Symbol]:
    """Fetch and cache Bitget spot symbol metadata."""
    if self.symbols_cache is None:
      self.symbols_cache = {s['symbol']: s for s in await self.client.spot.public.symbols()}
    return self.symbols_cache

  @SDK.method
  async def flows(self, start: datetime, end: datetime):
    """Fetch spot tax rows as unknown observations."""
    async for chunk in self.client.common.tax.spot_transaction_records_paged(start=start, end=end):
      for tx in chunk:
        observations: list[Observation] = [
          UnknownObservation(
            id=tx['id'],
            asset=tx['coin'],
            amount=tx['amount'],
            time=self.add_tz(tx['ts']),
            reason=tx['spotTaxType'],
          )
        ]
        if (fee := abs(tx['fee'])) > 0:
          observations.append(FeeLeg(
            id=f"{tx['id']}:fee",
            asset=tx['coin'],
            amount=-fee,
            time=self.add_tz(tx['ts']),
            event_type='unknown',
            event_id=tx['id'],
          ))
        yield api_record_many(
          observations,
          endpoint='spot_transaction_records',
          response=tx,
        )

  @SDK.method
  async def trades(self, start: datetime, end: datetime):
    """Fetch spot fills as trade observations."""
    symbols = await self.symbols
    async for chunk in self.client.spot.trade.fills_paged(start=start, end=end):
      for fill in chunk:
        base = symbols[fill['symbol']]['baseCoin']
        quote = symbols[fill['symbol']]['quoteCoin']
        yield api_record(Trade(
          id=fill['tradeId'],
          time=self.add_tz(fill['cTime']),
          base=base, quote=quote,
          pair=fill['symbol'],
          size=signed_size(fill['size'], fill['side']),
          price=fill['priceAvg'],
          order_id=fill['orderId'],
          trade_id=fill['tradeId'],
          fee=nonzero_fee(fill['feeDetail']['totalFee'], fill['feeDetail']['feeCoin']),
        ), endpoint='spot_fills', response=fill)

  @SDK.method
  async def deposits(self, start: datetime, end: datetime):
    """Fetch successful on-chain spot deposits."""
    async for chunk in self.client.spot.wallet.deposit_records_paged(start, end):
      for deposit in chunk:
        if deposit['dest'] != 'on_chain' or deposit['status'] != 'success':
          continue
        yield api_record(CryptoDeposit(
          id=deposit['tradeId'],
          time=self.add_tz(deposit['cTime']),
          asset=deposit['coin'],
          amount=deposit['size'],
          network=deposit['chain'],
          tx_id=deposit['tradeId'],
        ), endpoint='spot_deposits', response=deposit)
  
  @SDK.method
  async def withdrawals(self, start: datetime, end: datetime):
    """Fetch successful on-chain spot withdrawals."""
    async for chunk in self.client.spot.wallet.withdrawal_records_paged(start, end):
      for withdrawal in chunk:
        if withdrawal['dest'] != 'on_chain' or withdrawal['status'] != 'success':
          continue
        
        yield api_record(CryptoWithdrawal(
          id=withdrawal['tradeId'],
          time=self.add_tz(withdrawal['cTime']),
          asset=withdrawal['coin'],
          amount=-withdrawal['size'],
          network=withdrawal['chain'],
          tx_id=withdrawal['tradeId'],
          dst_address=withdrawal['toAddress'],
          fee=nonzero_fee(withdrawal['fee'], withdrawal['coin']),
        ), endpoint='spot_withdrawals', response=withdrawal)

  @SDK.method
  async def history(
    self, start: datetime | None = None, end: datetime | None = None
  ) -> AsyncIterable[Record]:
    """Fetch spot history records."""
    start, end = require_range(start, end)
    async for record in self.flows(start, end):
      yield record
    async for record in self.trades(start, end):
      yield record
    async for record in self.deposits(start, end):
      yield record
    async for record in self.withdrawals(start, end):
      yield record
