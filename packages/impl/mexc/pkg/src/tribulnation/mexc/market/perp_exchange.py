"""Public linear perpetual snapshots, preserving MEXC contract identifiers."""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from typed_mexc.schemas import ContractSpec, ContractTicker
from tribulnation.sdk.market import (
  PerpExchange as BasePerpExchange,
  PerpStats,
  Settings,
  Ticker,
)

from .impl import ExchangeMixin
from .perp_market import PerpMarket


def price(value: float | None) -> Decimal | None:
  """Treat an absent or zero quote as an empty side, not a tradable price."""
  return Decimal(str(value)) if value is not None and value > 0 else None


@dataclass(frozen=True)
class PerpExchange(ExchangeMixin, BasePerpExchange):
  """MEXC linear perpetual public market data; private methods are not enabled."""

  @property
  def venue_id(self) -> str:
    """The venue identifier."""
    return 'mexc'

  @property
  def exchange_id(self) -> str:
    """The linear perpetual exchange identifier."""
    return 'perp'

  async def markets(self) -> Sequence[str]:
    """List linear contracts, including contracts not enabled for API trading."""
    return list(await self.shared.load_perp_markets())

  async def market(self, market_id: str, /) -> PerpMarket:
    """Resolve an exact native contract symbol."""
    contracts = await self.shared.load_perp_markets()
    if market_id not in contracts:
      raise ValueError(f'Unknown MEXC linear perpetual market: {market_id!r}')
    return PerpMarket(shared=self.shared, info=contracts[market_id])

  async def selected_contracts(
    self,
    markets: Collection[str] | None,
  ) -> dict[str, ContractSpec]:
    """Resolve a selection without silently dropping unknown native market IDs."""
    contracts = await self.shared.load_perp_markets()
    if markets is None:
      return contracts
    wanted = set(markets)
    if unknown := wanted - contracts.keys():
      raise ValueError(
        f'Unknown MEXC linear perpetual markets: {", ".join(sorted(unknown))}'
      )
    return {symbol: info for symbol, info in contracts.items() if symbol in wanted}

  async def contract_tickers(self, markets: Collection[str]) -> list[ContractTicker]:
    """Require one bulk snapshot row for each selected/discovered linear market."""
    response = await self.call_mexc(
      lambda: self.client.futures.http.market.ticker(validate=self.shared.validate)
    )
    rows = response.get('data')
    if not isinstance(rows, list):
      raise ValueError('MEXC bulk perpetual tickers did not return a list')
    wanted = set(markets)
    selected: dict[str, ContractTicker] = {}
    for row in rows:
      symbol = row['symbol']
      if symbol not in wanted:
        continue
      if symbol in selected:
        raise ValueError(f'Duplicate MEXC perpetual ticker: {symbol}')
      selected[symbol] = row
    if missing := wanted - selected.keys():
      raise ValueError(
        f'MEXC perpetual snapshot missing markets: {", ".join(sorted(missing))}'
      )
    return list(selected.values())

  async def tickers(
    self,
    markets: Collection[str] | None = None,
    *,
    settings: Settings = {},
  ) -> Mapping[str, Ticker]:
    """Fetch all linear tickers in one call and convert contract volume to base units."""
    if markets is not None and not markets:
      return {}
    contracts = await self.selected_contracts(markets)
    return {
      row['symbol']: Ticker(
        last=price(row['lastPrice']),
        bid=price(row.get('bid1')),
        ask=price(row.get('ask1')),
        base_volume_24h=Decimal(str(row['volume24']))
        * Decimal(str(contracts[row['symbol']]['contractSize'])),
      )
      for row in await self.contract_tickers(contracts)
    }

  async def perp_stats(
    self,
    markets: Collection[str] | None = None,
    *,
    settings: Settings = {},
  ) -> Mapping[str, PerpStats]:
    """Fetch bulk funding/prices/OI; use next_funding for per-contract settlement state.

    MEXC's bulk ticker does not report the settlement time or interval. Those fields
    remain absent rather than synthesizing a schedule or issuing one request per market.
    """
    if markets is not None and not markets:
      return {}
    contracts = await self.selected_contracts(markets)
    return {
      row['symbol']: PerpStats(
        index=Decimal(str(row['indexPrice'])),
        mark=price(row['fairPrice']),
        funding=Decimal(str(row['fundingRate'])),
        open_interest=Decimal(str(row['holdVol']))
        * Decimal(str(contracts[row['symbol']]['contractSize'])),
      )
      for row in await self.contract_tickers(contracts)
    }
