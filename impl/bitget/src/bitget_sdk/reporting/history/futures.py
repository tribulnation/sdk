from typing_extensions import AsyncIterable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
import warnings

from trading_sdk.core import SDK
from trading_sdk.reporting.history import Flow, FuturesTrade, History

from bitget import Bitget
from bitget.futures.trade.fills import fill_direction

from .util import TimezoneMixin

@dataclass(kw_only=True)
class FuturesHistory(TimezoneMixin, History):
  client: Bitget

  @SDK.method
  async def flows(self, start: datetime, end: datetime):
    async for chunk in self.client.common.tax.futures_transaction_records_paged(start=start, end=end):
      for tx in chunk:
        yield Flow(
          asset=tx['marginCoin'],
          change=tx['amount'],
          time=self.add_tz(tx['ts']),
          event_tag=tx['futureTaxType'],
          raw=tx,
          source='bitget:futures_transaction_records',
        )
        if (fee := abs(tx['fee'])) > 0:
          yield Flow(
            asset=tx['marginCoin'], change=-fee,
            time=self.add_tz(tx['ts']),
            event_tag='fee',
            raw=tx,
            source='bitget:futures_transaction_records',
          )

  @SDK.method
  async def trades(self, start: datetime, end: datetime):
    async for chunk in self.client.futures.trade.all_fills_paged(start=start, end=end):
      for fill in chunk:
        if len(fill['feeDetail']) > 1:
          warnings.warn(f"UNEXPECTED: Multiple fee details for fill {fill['tradeId']}: {fill['feeDetail']}")
          fee = None
          fee_asset = None
        if not fill['feeDetail'] or (fee := abs(fill['feeDetail'][0]['totalFee'] or Decimal(0))) == 0:
          fee = None
          fee_asset = None
        else:
          fee_asset = fill['feeDetail'][0]['feeCoin']

        yield FuturesTrade(
          id=fill['tradeId'],
          time=self.add_tz(fill['cTime']),
          instrument=fill['symbol'],
          qty=fill['baseVolume'],
          price=fill['price'],
          liquidity=fill['tradeScope'],
          side=fill_direction(fill),
          fee=fee,
          fee_asset=fee_asset,
          raw=fill,
          source='bitget:futures_fills',
        )

  async def history(self, start: datetime, end: datetime) -> AsyncIterable[History.History]:
    flows = [f async for f in self.flows(start, end)]
    yield History.History(flows=flows)
    trades = [t async for t in self.trades(start, end)]
    yield History.History(events=trades)