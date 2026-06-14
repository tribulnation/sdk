from typing_extensions import AsyncIterable, Iterable, Literal
from dataclasses import dataclass, field
from datetime import datetime

from tribulnation.sdk.core import SDK
from tribulnation.sdk.reporting import FeeLeg, Observation, Record, SpotTrade, UnknownObservation
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
class MarginHistory(TimezoneMixin, SdkHistory):
  """Bitget margin account history."""
  client: Bitget
  symbols_cache: dict[str, Symbol] | None = field(kw_only=True, default=None)

  @property
  async def symbols(self) -> dict[str, Symbol]:
    """Fetch and cache Bitget spot symbol metadata."""
    if self.symbols_cache is None:
      self.symbols_cache = {s['symbol']: s for s in await self.client.spot.public.symbols()}
    return self.symbols_cache

  @SDK.method
  async def flows(self, margin_type: Literal['isolated', 'crossed'], start: datetime, end: datetime):
    """Fetch margin tax rows as unknown observations."""
    async for chunk in self.client.common.tax.margin_transaction_records_paged(margin_type, start=start, end=end):
      for tx in chunk:
        observations: list[Observation] = [
          UnknownObservation(
            id=tx['id'],
            asset=tx['coin'],
            amount=tx['amount'],
            time=self.add_tz(tx['ts']),
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
          endpoint=f'{margin_type}_margin_transaction_records',
          response=tx,
        )

  @SDK.method
  async def symbol_trades(self, margin_type: Literal['isolated', 'crossed'], symbol: str, start: datetime, end: datetime):
    """Fetch margin fills for one symbol as trade observations."""
    symbols = await self.symbols
    if margin_type == 'isolated':
      fn = self.client.margin.isolated.trade.fills_paged
    else:
      fn = self.client.margin.cross.trade.fills_paged
    async for chunk in fn(symbol, start=start, end=end):
      for fill in chunk:
        base = symbols[symbol]['baseCoin']
        quote = symbols[symbol]['quoteCoin']
        side = 'buy' if 'buy' in fill['side'] else 'sell'
        yield api_record(SpotTrade(
          id=fill['tradeId'],
          time=self.add_tz(fill['cTime']),
          base=base, quote=quote,
          pair=symbol,
          size=signed_size(fill['size'], side),
          price=fill['priceAvg'],
          order_id=fill['orderId'],
          fee=nonzero_fee(fill['feeDetail']['totalFee'], fill['feeDetail']['feeCoin']),
        ), endpoint=f'{margin_type}_margin_fills', response=fill)

  @SDK.method
  async def trades(self, margin_type: Literal['isolated', 'crossed'], symbols: Iterable[str], start: datetime, end: datetime):
    """Fetch margin fills for a set of symbols."""
    for symbol in symbols:
      chunk = [t async for t in self.symbol_trades(margin_type, symbol, start, end)]
      yield chunk


  async def history(
    self, start: datetime | None = None, end: datetime | None = None
  ) -> AsyncIterable[Record]:
    """Fetch margin history records."""
    start, end = require_range(start, end)
    for margin_type in ('crossed', 'isolated'):
      records = [record async for record in self.flows(margin_type, start, end)]
      for record in records:
        yield record
      symbols = {
        symbol
        for record in records
        if (
          record.provenance['source'] == 'api'
          and (response := record.provenance.get('response'))
          and isinstance(response, dict)
          and isinstance(symbol := response.get('symbol'), str)
        )
      }
      async for chunk in self.trades(margin_type, symbols, start, end):
        for record in chunk:
          yield record
