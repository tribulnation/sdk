"""dYdX placement failures stay ambiguous: none is `OrderRejected` yet (ADR 0043)."""

from decimal import Decimal
from types import SimpleNamespace
from typing_extensions import cast
from unittest.mock import AsyncMock

import pytest
from typed_core import exceptions as core

from tribulnation.dydx.market.impl.mixin import MarketMixin
from tribulnation.dydx.market.impl.orders import place_order
from tribulnation.sdk.core import ApiError, OrderRejected
from tribulnation.sdk.market import Order

ORDER: Order = {'type': 'MARKET', 'qty': Decimal('1'), 'price': Decimal('100')}


@pytest.mark.parametrize(
  'error',
  [
    core.ApiError('tx already exists in cache'),
    core.ApiError('dYdX transaction broadcast did not return a tx response'),
  ],
)
async def test_broadcast_failure_is_not_rejected(error: Exception):
  """`typed_dydx` drops the CheckTx code, so a refusal cannot be told from a pending tx."""
  market = cast(
    MarketMixin,
    SimpleNamespace(
      client=SimpleNamespace(
        node=SimpleNamespace(place_order=AsyncMock(side_effect=error))
      ),
      perpetual_market=object(),
      subaccount=0,
    ),
  )

  with pytest.raises(ApiError) as raised:
    await place_order(market, ORDER)

  assert not isinstance(raised.value, OrderRejected)
