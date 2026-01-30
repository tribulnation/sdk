from typing_extensions import AsyncIterable, Iterable, Literal
from dataclasses import dataclass, field
from datetime import datetime

from sdk.core import Stream, ChunkedStream
from sdk.reporting.transactions import (
  Flow, match_transactions,
  Transaction, Trade, Fee
)
from bitget import Bitget
from bitget.spot.market.symbols import Symbol

DEFAULT_TRANSACTION_TYPES: dict[str, Flow.Label] = {
  'margin_coupon_profit': 'bonus',
  'deal_in': 'trade',
  'deal_out': 'trade',
  'transfer_in': 'internal_transfer',
  'transfer_out': 'internal_transfer',
}
DEFAULT_IGNORE_TYPES: set[str] = set()

@dataclass
class MarginTransactions:
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

  @Stream.lift
  async def flows(self, margin_type: Literal['isolated', 'crossed'], start: datetime, end: datetime):
    async for chunk in self.client.common.tax.margin_transaction_records_paged(margin_type, start=start, end=end):
      for tx in chunk:
        if (type := self.transaction_type(tx['marginTaxType'])) is not None:
          yield Flow(
            asset=tx['coin'], change=tx['amount'],
            kind='currency', time=tx['ts'], details=tx,
            label=type,
          )
        if (fee := abs(tx['fee'])) > 0:
          yield Flow(
            asset=tx['coin'], change=-fee,
            kind='currency', time=tx['ts'],
            details=tx, label='fee',
          )

  @Stream.lift
  async def trades(self, margin_type: Literal['isolated', 'crossed'], symbols: Iterable[str], start: datetime, end: datetime):
    symbols_map = await self.symbols_map
    if margin_type == 'isolated':
      fn = self.client.margin.isolated.trade.fills_paged
    else:
      fn = self.client.margin.cross.trade.fills_paged
    for symbol in symbols:
      async for chunk in fn(symbol, start=start, end=end):
        for fill in chunk:
          base = symbols_map[symbol]['baseCoin']
          quote = symbols_map[symbol]['quoteCoin']
          fee = abs(fill['feeDetail']['totalFee'])
          fee = Fee(amount=fee, asset=fill['feeDetail']['feeCoin']) if fee > 0 else None
          yield Trade(
            id=fill['tradeId'],
            time=fill['cTime'],
            base=base, quote=quote,
            qty=fill['size'], price=fill['priceAvg'],
            liquidity=fill['tradeScope'],
            side='buy' if 'buy' in fill['side'] else 'sell',
            details=fill,
            fee=fee,
          )

  @ChunkedStream.lift
  async def __call__(self, start: datetime, end: datetime) -> AsyncIterable[list[Transaction]]:
    for margin_type in ('crossed', 'isolated'):
      flows = await self.flows(margin_type, start, end)
      symbols = set(f.details['symbol'] for f in flows if f.details['symbol'])
      trades = await self.trades(margin_type, symbols, start, end)
      matched_txs, other_flows = match_transactions(flows, trades)
      yield matched_txs
      yield [Transaction.single(flow.details['id'], flow) for flow in other_flows]