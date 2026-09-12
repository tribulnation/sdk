"""Best-effort history from Bitget's Classic margin endpoints."""

from typing_extensions import AsyncIterable, Iterable, Literal
from dataclasses import dataclass, field
from datetime import datetime

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
from typed_bitget.classic.spot.symbols import SpotSymbol

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
class MarginHistory(TimezoneMixin, SdkHistory):
  """Bitget margin account history."""

  client: Bitget
  symbols_cache: dict[str, SpotSymbol] | None = field(kw_only=True, default=None)

  @property
  async def symbols(self) -> dict[str, SpotSymbol]:
    """Fetch and cache Bitget spot symbol metadata."""
    if self.symbols_cache is None:
      self.symbols_cache = {
        s['symbol']: s for s in await self.client.classic.spot.symbols()
      }
    return self.symbols_cache

  @SDK.method
  async def flows(
    self, margin_type: Literal['isolated', 'crossed'], start: datetime, end: datetime
  ):
    """Fetch margin tax rows as unknown observations."""
    async for _, record in self.flow_records(margin_type, start, end):
      yield record

  async def flow_records(
    self, margin_type: Literal['isolated', 'crossed'], start: datetime, end: datetime
  ):
    """Keep the tax row's symbol alongside its observation for fill discovery."""
    async for chunk in self.client.classic.tax.margin_records_paged(
      margin_type, start_time=start, end_time=end
    ):
      for tx in chunk:
        subaccount = f'{margin_type}_margin'
        observations: list[Observation] = [
          UnknownObservation(
            id=tx['id'],
            asset=tx['coin'],
            amount=tx['amount'],
            time=self.add_tz(tx['ts']),
            subaccount=subaccount,
          )
        ]
        if (fee := abs(tx['fee'])) > 0:
          observations.append(
            FeeLeg(
              id=f'{tx["id"]}:fee',
              asset=tx['coin'],
              amount=-fee,
              time=self.add_tz(tx['ts']),
              event_type='unknown',
              event_id=tx['id'],
              subaccount=subaccount,
            )
          )
        yield (
          tx['symbol'],
          api_record_many(
            observations,
            endpoint=f'{margin_type}_margin_transaction_records',
            response=tx,
          ),
        )

  @SDK.method
  async def symbol_trades(
    self,
    margin_type: Literal['isolated', 'crossed'],
    symbol: str,
    start: datetime,
    end: datetime,
  ):
    """Fetch margin fills for one symbol as trade observations."""
    symbols = await self.symbols
    if margin_type == 'isolated':
      fn = self.client.classic.margin.isolated.order.fills_paged
    else:
      fn = self.client.classic.margin.cross.order.fills_paged
    async for chunk in fn(symbol=symbol, start_time=start, end_time=end):
      for fill in chunk:
        subaccount = f'{margin_type}_margin'
        base = symbols[symbol]['baseCoin']
        quote = symbols[symbol]['quoteCoin']
        direction = fill.get('side')
        side = 'buy' if direction is not None and 'buy' in direction else 'sell'
        size = fill.get('size')
        time = fill.get('cTime')
        fee_detail = fill.get('feeDetail')
        fee_amount = fee_detail.get('totalFee') if fee_detail is not None else None
        fee_asset = fee_detail.get('feeCoin') if fee_detail is not None else None
        yield api_record(
          SpotTrade(
            id=fill.get('tradeId'),
            time=self.add_tz(time) if time is not None else None,
            base=base,
            quote=quote,
            pair=symbol,
            size=signed_size(size, side)
            if size is not None and direction is not None
            else None,
            price=fill.get('priceAvg'),
            order_id=fill.get('orderId'),
            fee=nonzero_fee(fee_amount, fee_asset)
            if fee_amount is not None and fee_asset is not None
            else None,
            subaccount=subaccount,
          ),
          endpoint=f'{margin_type}_margin_fills',
          response=fill,
        )

  @SDK.method
  async def trades(
    self,
    margin_type: Literal['isolated', 'crossed'],
    symbols: Iterable[str],
    start: datetime,
    end: datetime,
  ):
    """Fetch margin fills for a set of symbols."""
    for symbol in symbols:
      chunk = [t async for t in self.symbol_trades(margin_type, symbol, start, end)]
      yield chunk

  async def history(
    self, start: datetime | None = None, end: datetime | None = None
  ) -> AsyncIterable[HistoryRecord]:
    """Fetch margin history records."""
    start, end = require_range(start, end)
    for lower, upper in windows(start, end):
      for margin_type in ('crossed', 'isolated'):
        symbols: set[str] = set()
        async for symbol, record in self.flow_records(margin_type, lower, upper):
          if symbol:
            symbols.add(symbol)
          yield record
        async for chunk in self.trades(margin_type, symbols, lower, upper):
          for record in chunk:
            yield record
