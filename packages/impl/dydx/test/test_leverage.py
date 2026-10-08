"""Market leverage from the effective initial margin fraction, and available notional."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

from typing_extensions import Any, cast

from typed_dydx import Dydx
from typed_dydx.indexer.schemas import PerpetualMarket
from tribulnation.dydx.market.impl.mixin import Shared
from tribulnation.dydx.market.market import Market

ADDRESS = 'dydx1test'


def perpetual(**fields: Any) -> PerpetualMarket:
  """An ETC-USD market below its open-interest caps: 10% IMF, 10x."""
  row: dict[str, Any] = {
    'ticker': 'ETC-USD',
    'clobPairId': '1',
    'oraclePrice': '10',
    'openInterest': Decimal(100),
    'initialMarginFraction': Decimal('0.1'),
    'maintenanceMarginFraction': Decimal('0.05'),
    'openInterestLowerCap': Decimal(5000),
    'openInterestUpperCap': Decimal(10000),
  }
  row.update(fields)
  return cast(PerpetualMarket, row)


def market(*markets: PerpetualMarket) -> tuple[Market, SimpleNamespace]:
  """A market over a stub indexer returning one market list per `get_markets` call."""
  data = SimpleNamespace(
    get_markets=AsyncMock(side_effect=[{'markets': {'ETC-USD': m}} for m in markets]),
    get_subaccount=AsyncMock(
      return_value={
        'subaccount': {
          'equity': '150',
          'freeCollateral': '120',
          'openPerpetualPositions': {},
        }
      }
    ),
  )
  client = cast(Dydx, SimpleNamespace(indexer=SimpleNamespace(data=data)))
  shared = Shared(client=client, address=ADDRESS)
  return Market(shared=shared, perpetual_market=markets[0]), data


async def test_leverage_is_the_inverse_effective_imf_and_cached():
  """10% IMF is 10x; the cached market list is reused until `refetch=True`."""
  # Open notional 7500 sits halfway between the caps: IMF 0.1 + 0.5 * 0.9 = 0.55.
  m, data = market(perpetual(), perpetual(openInterest=Decimal(750)))
  assert await m.leverage() == 10
  assert await m.leverage() == 10
  assert data.get_markets.await_count == 1
  assert await m.leverage(refetch=True) == Decimal(1) / Decimal('0.55')
  assert data.get_markets.await_count == 2


async def test_available_notional_defaults_to_free_collateral_times_leverage():
  """The SDK default: the subaccount's `freeCollateral` times the leverage."""
  m, data = market(perpetual())
  assert await m.available_notional() == Decimal(1200)
  data.get_subaccount.assert_awaited_with(address=ADDRESS, subaccount=0)


async def test_whole_leverage_has_no_exponent():
  """`1 / 0.1` is shown as `10`, not `1E+1`."""
  m, _ = market(perpetual())
  assert str(await m.leverage()) == '10'
