"""Spot balances and collateral IDs on a unified account (ADR 0051)."""

from decimal import Decimal
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from typing_extensions import Any, cast
from typed_hyperliquid import Hyperliquid

from tribulnation.hyperliquid.market.impl.mixin import PerpMeta, Shared, SpotMeta
from tribulnation.hyperliquid.market.perps_market import PerpMarket
from tribulnation.hyperliquid.market.spot_exchange import SpotExchange
from tribulnation.hyperliquid.market.spot_market import SpotMarket
from tribulnation.sdk.market import (
  Balance,
  SpotBalances,
  SpotCollateralIds,
  SpotRules,
  is_perp,
  is_spot,
)

ADDRESS = '0x0000000000000000000000000000000000000001'
UBTC, USDC = 197, 0
"""Token indices: the venue's asset IDs."""


def shared() -> Shared:
  """A client stub answering one spot clearinghouse state: UBTC and USDC held."""
  state: dict[str, Any] = {
    'balances': [
      {'coin': 'USDC', 'token': USDC, 'total': Decimal(120), 'hold': Decimal(20)},
      {'coin': 'UBTC', 'token': UBTC, 'total': Decimal(2), 'hold': Decimal('0.5')},
    ]
  }
  info = SimpleNamespace(spot_clearinghouse_state=AsyncMock(return_value=state))
  return Shared(
    client=cast(Hyperliquid, SimpleNamespace(info=info)),
    maybe_address=ADDRESS,
    account_id='hl',
  )


def spot(shared: Shared) -> SpotMarket:
  """UBTC/USDC spot."""
  meta = cast(
    SpotMeta,
    {
      'asset_meta': {'index': 142, 'name': '@142', 'tokens': [UBTC, USDC]},
      'base_meta': {'index': UBTC, 'name': 'UBTC', 'szDecimals': 5},
      'quote_meta': {'index': USDC, 'name': 'USDC', 'szDecimals': 8},
    },
  )
  return SpotMarket(shared=shared, meta=meta)


def perp(shared: Shared) -> PerpMarket:
  """A perpetual whose dex is collateralised in USDC."""
  asset: dict[str, Any] = {'name': 'ETH', 'maxLeverage': 25, 'szDecimals': 4}
  meta = cast(
    PerpMeta,
    {
      'asset_idx': 1,
      'asset_meta': asset,
      'collateral_meta': {'index': USDC, 'name': 'USDC'},
    },
  )
  return PerpMarket(shared=shared, dex=None, meta=meta)


async def test_spot_balances_free_excludes_holds():
  """`free = total - hold` for base and quote, from one request."""
  s = shared()
  assert await spot(s).balances() == SpotBalances(
    base=Balance(total=Decimal(2), free=Decimal('1.5')),
    quote=Balance(total=Decimal(120), free=Decimal(100)),
  )
  cast(Any, s.client.info).spot_clearinghouse_state.assert_awaited_once_with(
    user=ADDRESS
  )


async def test_perp_shares_the_spot_quote_collateral_id(
  monkeypatch: pytest.MonkeyPatch,
):
  """Unified account: the perp pool is the dex collateral token's spot balance."""
  rules = SpotRules(
    base=str(UBTC),
    quote=str(USDC),
    fee_asset=None,
    tick_size=Decimal('0.1'),
    step_size=Decimal('0.00001'),
    api=True,
  )
  monkeypatch.setattr(SpotMarket, 'rules', AsyncMock(return_value=rules))
  s = shared()
  ids = await spot(s).collateral_ids()
  assert ids == SpotCollateralIds(base=f'hl:spot:{UBTC}', quote=f'hl:spot:{USDC}')
  assert await perp(s).collateral_id() == ids.quote


async def test_spot_exchange_balance_by_token_index():
  """The resolver's spot hook reads one token; names are not asset IDs."""
  exchange = SpotExchange(shared=shared())
  assert await exchange.balance(str(UBTC)) == Balance(
    total=Decimal(2), free=Decimal('1.5')
  )
  assert await exchange.balance('5') == Balance(total=Decimal(0), free=Decimal(0))
  with pytest.raises(ValueError, match='token indices'):
    await exchange.balance('USDC')


def test_kinds_narrow():
  """`is_spot`/`is_perp` and `kind` tell the market types apart."""
  s = shared()
  assert is_spot(spot(s)) and not is_perp(spot(s)) and spot(s).kind == 'spot'
  assert is_perp(perp(s)) and not is_spot(perp(s)) and perp(s).kind == 'perp'
  assert is_spot(SpotExchange(shared=s))


async def test_spot_rules_name_the_token_indices(monkeypatch: pytest.MonkeyPatch):
  """`SpotRules.base`/`quote` are token indices, the venue's asset IDs."""
  module = importlib.import_module('tribulnation.hyperliquid.market.impl.spot_rules')
  monkeypatch.setattr(module, 'standard_spot_fees', AsyncMock(return_value=None))
  rules = await spot(shared()).rules()
  assert (rules.base, rules.quote) == (str(UBTC), str(USDC))
