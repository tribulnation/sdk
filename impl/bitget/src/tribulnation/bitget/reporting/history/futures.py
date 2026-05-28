from typing_extensions import AsyncIterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import warnings

from tribulnation.sdk.core import SDK
from tribulnation.sdk.reporting import FeeLeg, Observation, Record, SpotTrade, UnknownObservation
from tribulnation.sdk.reporting import History as SdkHistory

from bitget import Bitget
from bitget.futures.trade.fills import fill_direction

from .util import (
  TimezoneMixin,
  api_record,
  api_record_many,
  nonzero_fee,
  require_range,
  signed_size,
)

@dataclass(kw_only=True)
class FuturesHistory(TimezoneMixin, SdkHistory):
  """Bitget futures account history."""
  client: Bitget

  @SDK.method
  async def flows(self, start: datetime, end: datetime):
    """Fetch futures tax rows as unknown observations."""
    async for chunk in self.client.common.tax.futures_transaction_records_paged(start=start, end=end):
      for tx in chunk:
        observations: list[Observation] = [
          UnknownObservation(
            id=tx['id'],
            asset=tx['marginCoin'],
            amount=tx['amount'],
            time=self.add_tz(tx['ts']),
            reason=tx['futureTaxType'],
          )
        ]
        if (fee := abs(tx['fee'])) > 0:
          observations.append(FeeLeg(
            id=f"{tx['id']}:fee",
            asset=tx['marginCoin'],
            amount=-fee,
            time=self.add_tz(tx['ts']),
            event_type='unknown',
            event_id=tx['id'],
          ))
        yield api_record_many(
          observations,
          endpoint='futures_transaction_records',
          response=tx,
        )

  @SDK.method
  async def trades(self, start: datetime, end: datetime):
    """Fetch futures fills as trade observations."""
    async for chunk in self.client.futures.trade.all_fills_paged(start=start, end=end):
      for fill in chunk:
        if len(fill['feeDetail']) > 1:
          warnings.warn(f"UNEXPECTED: Multiple fee details for fill {fill['tradeId']}: {fill['feeDetail']}")
          fee = None
          fee_asset = None
        elif not fill['feeDetail'] or (fee := abs(fill['feeDetail'][0]['totalFee'] or Decimal(0))) == 0:
          fee = None
          fee_asset = None
        else:
          fee_asset = fill['feeDetail'][0]['feeCoin']

        side = fill_direction(fill)
        yield api_record(SpotTrade(
          id=fill['tradeId'],
          time=self.add_tz(fill['cTime']),
          pair=fill['symbol'],
          size=signed_size(fill['baseVolume'], side),
          price=fill['price'],
          order_id=fill['orderId'],
          fee=None if fee is None or fee_asset is None else nonzero_fee(fee, fee_asset),
        ), endpoint='futures_fills', response=fill)

  async def history(
    self, start: datetime | None = None, end: datetime | None = None
  ) -> AsyncIterable[Record]:
    """Fetch futures history records."""
    start, end = require_range(start, end)
    async for record in self.flows(start, end):
      yield record
    async for record in self.trades(start, end):
      yield record
