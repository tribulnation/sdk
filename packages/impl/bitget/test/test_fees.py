"""Account fee reads route by account mode and never substitute public rates."""

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from typed_bitget import Bitget
from typed_bitget.classic.common.trade_rate import TradeRateEndpoint
from typed_bitget.uta.account.fee_rate import FeeRateEndpoint

from tribulnation.bitget.core import SdkMixin
from tribulnation.bitget.market import PerpMarket, SpotMarket
from tribulnation.sdk.market import Fees


@pytest.mark.parametrize('uta', [True, False])
@pytest.mark.parametrize('perp', [True, False])
async def test_personal_rates_use_account_mode(
  uta: bool, perp: bool, monkeypatch: pytest.MonkeyPatch
):
  """A negative maker rebate and zero taker fee remain valid on both sides."""
  request = AsyncMock(
    return_value={'makerFeeRate': Decimal('-0.0001'), 'takerFeeRate': Decimal(0)}
  )
  other = AsyncMock(side_effect=AssertionError('wrong account mode'))
  monkeypatch.setattr(FeeRateEndpoint, 'fee_rate', request if uta else other)
  monkeypatch.setattr(TradeRateEndpoint, 'trade_rate', other if uta else request)
  account = SdkMixin(client=Bitget.new(public=True), uta=uta)
  market = (PerpMarket if perp else SpotMarket)(account=account, symbol='BTCUSDT')
  assert await market.fees() == Fees.symmetric(
    maker=Decimal('-0.0001'), taker=Decimal(0)
  )
  if uta:
    request.assert_awaited_once_with(
      'USDT-FUTURES' if perp else 'SPOT', symbol='BTCUSDT', validate=True
    )
  else:
    request.assert_awaited_once_with(
      'BTCUSDT', business_type='mix' if perp else 'spot', validate=True
    )
  other.assert_not_awaited()
