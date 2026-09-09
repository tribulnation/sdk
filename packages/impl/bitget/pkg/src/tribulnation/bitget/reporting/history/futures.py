"""Best-effort history from Bitget's Classic futures endpoints."""

from typing_extensions import AsyncIterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import warnings

from tribulnation.sdk.core import SDK
from tribulnation.sdk.reporting import (
  FeeLeg,
  Observation,
  HistoryRecord,
  SpotTrade,
  UnknownObservation,
)
from tribulnation.sdk.reporting import History as SdkHistory

from typed_bitget import Bitget

from .util import (
  TimezoneMixin,
  api_record,
  api_record_many,
  nonzero_fee,
  require_range,
  signed_size,
  windows,
)


@dataclass(kw_only=True)
class FuturesHistory(TimezoneMixin, SdkHistory):
  """Bitget futures account history."""

  client: Bitget

  @SDK.method
  async def flows(self, start: datetime, end: datetime):
    """Fetch futures tax rows as unknown observations."""
    async for chunk in self.client.classic.tax.futures_records_paged(
      start_time=start, end_time=end
    ):
      for tx in chunk:
        observations: list[Observation] = [
          UnknownObservation(
            id=tx['id'],
            asset=tx['marginCoin'],
            amount=tx['amount'],
            time=self.add_tz(tx['ts']),
            subaccount='futures',
          )
        ]
        if (fee := abs(tx['fee'])) > 0:
          observations.append(
            FeeLeg(
              id=f'{tx["id"]}:fee',
              asset=tx['marginCoin'],
              amount=-fee,
              time=self.add_tz(tx['ts']),
              event_type='unknown',
              event_id=tx['id'],
              subaccount='futures',
            )
          )
        yield api_record_many(
          observations,
          endpoint='futures_transaction_records',
          response=tx,
        )

  @SDK.method
  async def trades(self, start: datetime, end: datetime):
    """Fetch futures fills as trade observations."""
    async for chunk in self.client.classic.mix.order.fill_history_paged(
      product_type='USDT-FUTURES', start_time=start, end_time=end
    ):
      for fill in chunk:
        if len(fill['feeDetail']) > 1:
          warnings.warn(
            'Bitget futures fill has multiple fee details; aggregate fee is unknown.'
          )
          fee = None
          fee_asset = None
        elif (
          not fill['feeDetail']
          or (fee := abs(Decimal(fill['feeDetail'][0]['totalFee']))) == 0
        ):
          fee = None
          fee_asset = None
        else:
          fee_asset = fill['feeDetail'][0]['feeCoin']

        side = fill['side']
        yield api_record(
          SpotTrade(
            id=fill['tradeId'],
            time=self.add_tz(fill['cTime']),
            pair=fill['symbol'],
            size=signed_size(Decimal(fill['baseVolume']), side),
            price=Decimal(fill['price']),
            order_id=fill['orderId'],
            fee=None
            if fee is None or fee_asset is None
            else nonzero_fee(fee, fee_asset),
            subaccount='futures',
          ),
          endpoint='futures_fills',
          response=fill,
        )

  async def history(
    self, start: datetime | None = None, end: datetime | None = None
  ) -> AsyncIterable[HistoryRecord]:
    """Fetch futures history records."""
    start, end = require_range(start, end)
    for lower, upper in windows(start, end):
      async for record in self.flows(lower, upper):
        yield record
      async for record in self.trades(lower, upper):
        yield record
