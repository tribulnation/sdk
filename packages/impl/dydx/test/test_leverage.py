"""Market leverage from the effective and the subaccount's own initial margin fraction,
`set_leverage`, and available notional."""

import logging
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from typing_extensions import Any, cast

from tribulnation.sdk.core import AuthError
from typed_core.exceptions import AuthError as TypedAuthError
from typed_dydx import Dydx
from typed_dydx.indexer.schemas import PerpetualMarket
from typed_dydx.protos.dydxprotocol import clob
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


def settings(*entries: tuple[int, int]) -> clob.QueryLeverageResponse:
  """The chain's leverage settings of a subaccount: `(clob pair id, imf ppm)` pairs."""
  return clob.QueryLeverageResponse(
    clob_pair_leverage=[
      clob.ClobPairLeverageInfo(clob_pair_id=pair, custom_imf_ppm=ppm)
      for pair, ppm in entries
    ]
  )


def market(
  *markets: PerpetualMarket,
  leverage: clob.QueryLeverageResponse | None = None,
  wallet: bool = True,
  subaccount: int = 0,
) -> tuple[Market, SimpleNamespace]:
  """A market over a stub indexer returning one market list per `get_markets` call,
  a stub chain answering the subaccount's leverage settings, and a stub node."""
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
  data.leverage = AsyncMock(return_value=leverage or settings())
  data.update_leverage = AsyncMock()

  def require_wallet():
    """The stub wallet, or the node's refusal without one."""
    if not wallet:
      raise TypedAuthError('A wallet is required')
    return SimpleNamespace(address=ADDRESS)

  client = cast(
    Dydx,
    SimpleNamespace(
      indexer=SimpleNamespace(data=data),
      chain=SimpleNamespace(clob=SimpleNamespace(leverage=data.leverage)),
      node=SimpleNamespace(
        require_wallet=require_wallet, update_leverage=data.update_leverage
      ),
    ),
  )
  shared = Shared(client=client, address=ADDRESS)
  return Market(shared=shared, perpetual_market=markets[0], subaccount=subaccount), data


async def test_leverage_is_the_inverse_effective_imf_and_cached():
  """10% IMF is 10x; the cached market list is reused, whatever the `ttl`, until
  it is reloaded (`rules(refetch=True)`, tickers and perpetual stats do)."""
  # Open notional 7500 sits halfway between the caps: IMF 0.1 + 0.5 * 0.9 = 0.55.
  m, data = market(perpetual(), perpetual(openInterest=Decimal(750)))
  assert await m.leverage() == 10
  assert await m.leverage(ttl=None) == 10
  assert data.get_markets.await_count == 1
  await m.shared.load_markets(refetch=True)
  assert await m.leverage() == Decimal(1) / Decimal('0.55')
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


async def test_leverage_is_capped_by_the_subaccount_setting():
  """A custom IMF above the market's caps leverage at its inverse; one for another
  market, or below the effective IMF, changes nothing (the chain margins the larger)."""
  m, data = market(perpetual(), leverage=settings((1, 400_000), (2, 1_000_000)))
  assert await m.leverage() == Decimal('2.5')
  data.leverage.assert_awaited_with(ADDRESS, number=0)
  m, _ = market(perpetual(), leverage=settings((1, 50_000)))
  assert await m.leverage() == 10
  m, _ = market(perpetual(), leverage=settings((1, 200_000)))
  assert str(await m.leverage()) == '5'


async def test_leverage_reads_the_addressed_subaccount():
  """A child subaccount's setting is its own."""
  m, data = market(perpetual(), subaccount=128)
  await m.leverage()
  data.leverage.assert_awaited_with(ADDRESS, number=128)


async def test_set_leverage_sends_the_whole_ppm_fraction_simulated_first(
  caplog: pytest.LogCaptureFixture,
):
  """5x is 200 000 ppm on the market's CLOB pair, for the addressed subaccount,
  simulated before broadcast, and logged at INFO."""
  m, data = market(perpetual(), subaccount=3)
  with caplog.at_level(logging.INFO, logger='tribulnation.dydx.market.market'):
    await m.set_leverage(Decimal(5))
  data.update_leverage.assert_awaited_once_with(
    {1: 200_000}, subaccount=3, simulate=True
  )
  assert f'{m.id}: leverage set to 5' in caplog.messages
  await m.set_leverage(Decimal('2.5'))
  data.update_leverage.assert_awaited_with({1: 400_000}, subaccount=3, simulate=True)
  await m.set_leverage(Decimal(1))
  data.update_leverage.assert_awaited_with({1: 1_000_000}, subaccount=3, simulate=True)


@pytest.mark.parametrize(
  'leverage',
  ['3', '0', '-2', '0.5', '11', 'NaN', 'Infinity', '7'],
)
async def test_set_leverage_refuses_values_the_chain_cannot_carry(leverage: str):
  """Without a whole ppm fraction (3x, 7x), below 1x, above the market's 10x maximum,
  or not a positive finite number: refused before anything is sent."""
  m, data = market(perpetual())
  with pytest.raises(ValueError):
    await m.set_leverage(Decimal(leverage))
  data.update_leverage.assert_not_awaited()


async def test_set_leverage_needs_a_wallet():
  """An address alone reads leverage but cannot set it."""
  m, data = market(perpetual(), wallet=False)
  with pytest.raises(AuthError):
    await m.set_leverage(Decimal(5))
  data.update_leverage.assert_not_awaited()
