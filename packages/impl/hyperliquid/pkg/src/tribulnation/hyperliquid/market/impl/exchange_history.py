"""Account-wide history scoped to a Hyperliquid spot or perpetual exchange."""

from datetime import datetime
from decimal import Decimal
from typing_extensions import AsyncIterable, Callable, Sequence

from tribulnation.sdk.market import ExchangeFundingPayment, ExchangeTrade, Trade

from .mixin import PerpMixin, SpotMixin


def perp_market_id(coin: str, dex: str | None) -> str | None:
  """Keep default or builder perpetuals without requiring a current listing."""
  if coin.startswith('@') or '/' in coin:
    return None
  if dex is None:
    return coin if ':' not in coin else None
  return coin if coin.startswith(f'{dex}:') else None


async def market_resolver(
  owner: SpotMixin | PerpMixin,
) -> Callable[[str], str | None]:
  """Resolve native fill coins into this exchange's canonical market IDs."""
  if isinstance(owner, PerpMixin):
    return lambda coin: perp_market_id(coin, owner.dex_name)

  meta = await owner.shared.load_spot_meta()
  tokens = {token['index']: token['name'] for token in meta['tokens']}
  markets: dict[str, str] = {}
  for pair in meta['universe']:
    base, quote = pair['tokens']
    market_id = f'{tokens[base]}/{tokens[quote]}:{pair["index"]}'
    markets[pair['name']] = market_id
    markets[f'@{pair["index"]}'] = market_id

  def resolve(coin: str) -> str | None:
    """Ignore perpetuals and refuse to silently drop unresolvable spot fills."""
    if coin in markets:
      return markets[coin]
    if coin.startswith('@') or '/' in coin:
      raise ValueError(f'No spot metadata for historical market {coin!r}')
    return None

  return resolve


async def exchange_trades_history(
  owner: SpotMixin | PerpMixin, *, start: datetime, end: datetime
) -> AsyncIterable[Sequence[ExchangeTrade]]:
  """Walk the native account fills once, retaining only this exchange's rows."""
  resolve = await market_resolver(owner)
  async for chunk in owner.client.info.user_fills_by_time_paged(
    user=owner.address, start_time=start, end_time=end
  ).via(owner.call_hyperliquid):
    trades: list[ExchangeTrade] = []
    for fill in chunk:
      time = fill['time'].astimezone()
      if time < start or time > end:
        continue
      market_id = resolve(fill['coin'])
      if market_id is None:
        continue
      trades.append(
        ExchangeTrade(
          market_id=market_id,
          id=str(fill['tid']),
          price=Decimal(fill['px']),
          qty=Decimal(fill['sz']) * (1 if fill['side'] == 'B' else -1),
          time=time,
          maker=not fill.get('crossed', False),
          fee=Trade.Fee(
            amount=Decimal(fill['fee']),
            asset=await owner.shared.resolve_asset_index(fill['feeToken']),
          ),
          details=fill,
        )
      )
    if trades:
      yield trades


async def exchange_funding_payments(
  owner: PerpMixin, *, start: datetime, end: datetime
) -> AsyncIterable[Sequence[ExchangeFundingPayment]]:
  """Walk native account funding once, keeping only this perpetual DEX."""
  async for chunk in owner.client.info.user_funding_paged(
    user=owner.address, start_time=start, end_time=end
  ).via(owner.call_hyperliquid):
    payments: list[ExchangeFundingPayment] = []
    for payment in chunk:
      market_id = perp_market_id(payment['delta']['coin'], owner.dex_name)
      time = payment['time'].astimezone()
      if market_id is None or time < start or time > end:
        continue
      payments.append(
        ExchangeFundingPayment(
          market_id=market_id,
          amount=-Decimal(payment['delta']['usdc']),
          time=time,
        )
      )
    if payments:
      yield payments
