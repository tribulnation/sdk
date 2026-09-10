"""MEXC spot standard metadata and undiscounted personal fee contracts."""

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from typing_extensions import cast
from typed_mexc.spot.http.market.exchange_info import SymbolInfo

from tribulnation.mexc import MexcMarket
from tribulnation.mexc.market.spot_market import SpotMarket
from tribulnation.sdk.market import Fees


def market(venue: MexcMarket) -> SpotMarket:
  """Construct metadata without private discovery calls or live credentials."""
  return SpotMarket(
    shared=venue.shared,
    meta={
      'info': cast(
        SymbolInfo,
        {
          'symbol': 'BTCUSDT',
          'baseAsset': 'BTC',
          'quoteAsset': 'USDT',
          'quotePrecision': 2,
          'baseSizePrecision': '0.00001',
          'makerCommission': Decimal(0),
          'takerCommission': Decimal('0.0005'),
          'isSpotTradingAllowed': True,
        },
      )
    },
  )


async def test_standard_spot_fees_use_public_metadata(monkeypatch: pytest.MonkeyPatch):
  """Public commission fields preserve zero without consulting personal rates."""
  async with MexcMarket.public() as venue:
    private = AsyncMock(side_effect=AssertionError('Personal fees requested'))
    monkeypatch.setattr(venue.client.spot.http.account, 'trade_fee', private)
    assert (await market(venue).rules()).fees == Fees.symmetric(
      maker=Decimal(0),
      taker=Decimal('0.0005'),
    )
    private.assert_not_awaited()


@pytest.mark.parametrize('enabled', [False, True])
async def test_personal_spot_fee_discount_boundary(
  monkeypatch: pytest.MonkeyPatch,
  enabled: bool,
):
  """Unseparated optional deductions fail explicitly instead of altering quotes."""
  async with MexcMarket.public() as venue:
    account = venue.client.spot.http.account
    monkeypatch.setattr(
      account,
      'mx_deduct_status',
      AsyncMock(
        return_value={
          'data': {'mxDeductEnable': enabled},
        }
      ),
    )
    source = AsyncMock(
      return_value={
        'data': {
          'makerCommission': -0.0001,
          'takerCommission': 0.0005,
        }
      }
    )
    monkeypatch.setattr(account, 'trade_fee', source)
    if enabled:
      with pytest.raises(NotImplementedError, match='MX deduction enabled'):
        await market(venue).fees()
      source.assert_not_awaited()
    else:
      assert await market(venue).fees() == Fees.symmetric(
        maker=Decimal('-0.0001'),
        taker=Decimal('0.0005'),
      )
      source.assert_awaited_once_with('BTCUSDT', validate=True)


async def test_personal_spot_missing_rate_does_not_fallback(
  monkeypatch: pytest.MonkeyPatch,
):
  """A malformed personal response does not reuse public metadata rates."""
  async with MexcMarket.public() as venue:
    account = venue.client.spot.http.account
    monkeypatch.setattr(
      account,
      'mx_deduct_status',
      AsyncMock(
        return_value={
          'data': {'mxDeductEnable': False},
        }
      ),
    )
    monkeypatch.setattr(
      account,
      'trade_fee',
      AsyncMock(
        return_value={
          'data': {'makerCommission': 0},
        }
      ),
    )
    with pytest.raises(KeyError, match='takerCommission'):
      await market(venue).fees()
