from typing_extensions import AsyncIterable, Iterable, Literal
from dataclasses import dataclass, field
from datetime import datetime

from trading_sdk.core import SDK
from trading_sdk.reporting.history import Flow, SpotTrade, History
from bitget import Bitget
from bitget.spot.public.symbols import Symbol

@dataclass
class MarginHistory(History):
  client: Bitget
  symbols_cache: dict[str, Symbol] | None = field(kw_only=True, default=None)

  @property
  async def symbols(self) -> dict[str, Symbol]:
    if self.symbols_cache is None:
      self.symbols_cache = {s['symbol']: s for s in await self.client.spot.public.symbols()}
    return self.symbols_cache

  @SDK.method
  async def flows(self, margin_type: Literal['isolated', 'crossed'], start: datetime, end: datetime):
    async for chunk in self.client.common.tax.margin_transaction_records_paged(margin_type, start=start, end=end):
      for tx in chunk:
        yield Flow(
          asset=tx['coin'], change=tx['amount'],
          time=tx['ts'], raw=tx,
          event_tag=tx['marginTaxType'],
          source='bitget:margin_transaction_records',
        )
        if (fee := abs(tx['fee'])) > 0:
          yield Flow(
            asset=tx['coin'], change=-fee,
            time=tx['ts'], raw=tx,
            event_tag='fee',
            source='bitget:margin_transaction_records',
          )

  @SDK.method
  async def symbol_trades(self, margin_type: Literal['isolated', 'crossed'], symbol: str, start: datetime, end: datetime):
    symbols = await self.symbols
    if margin_type == 'isolated':
      fn = self.client.margin.isolated.trade.fills_paged
    else:
      fn = self.client.margin.cross.trade.fills_paged
    async for chunk in fn(symbol, start=start, end=end):
      for fill in chunk:
        base = symbols[symbol]['baseCoin']
        quote = symbols[symbol]['quoteCoin']
        yield SpotTrade(
          id=fill['tradeId'],
          time=fill['cTime'],
          base=base, quote=quote,
          qty=fill['size'], price=fill['priceAvg'],
          liquidity=fill['tradeScope'],
          side='buy' if 'buy' in fill['side'] else 'sell',
          fee=abs(fill['feeDetail']['totalFee']),
          fee_asset=fill['feeDetail']['feeCoin'],
          raw=fill,
          source='bitget:margin_fills',
        )

  @SDK.method
  async def trades(self, margin_type: Literal['isolated', 'crossed'], symbols: Iterable[str], start: datetime, end: datetime):
    symbols = await self.symbols
    for symbol in symbols:
      chunk = [t async for t in self.symbol_trades(margin_type, symbol, start, end)]
      yield chunk


  async def history(self, start: datetime, end: datetime) -> AsyncIterable[History.History]:
    for margin_type in ('crossed', 'isolated'):
      flows = [f async for f in self.flows(margin_type, start, end)]
      yield History.History(flows=flows)
      symbols = set(s for f in flows if (s := f.raw['symbol']))
      async for chunk in self.trades(margin_type, symbols, start, end):
        yield History.History(events=chunk)