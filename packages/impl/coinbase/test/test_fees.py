"""Unresolved account adjustments cannot be returned as combined fees."""

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from typed_coinbase import Coinbase
from typed_coinbase.app.advanced_trade.http.fees.transaction_summary import (
  TransactionSummary,
)

from tribulnation.coinbase.core.mixin import Shared
from tribulnation.coinbase.market import PerpMarket, SpotMarket
from tribulnation.sdk.market import Fees


def shared() -> Shared:
  """Build a credential-free fixture; every account request is mocked."""
  return Shared(client=Coinbase.new(public=True))


async def test_spot_does_not_claim_a_generic_tier_covers_stablepairs():
  """The global summary does not resolve per-product spot pricing."""
  market = SpotMarket(shared=shared(), product_id='USDC-USD')
  with pytest.raises(NotImplementedError, match='stablepair'):
    await market.fees()


@pytest.mark.parametrize(
  'extra',
  [
    {'has_cost_plus_commission': True},
    {'goods_and_services_tax': {'rate': Decimal('0.09'), 'type': 'EXCLUSIVE'}},
    {'goods_and_services_tax': {'rate': Decimal('0.09')}},
  ],
)
async def test_unresolved_account_adjustments_raise(
  extra: dict[str, object], monkeypatch: pytest.MonkeyPatch
):
  """Known extra components must not be silently dropped from the account rate."""
  request = AsyncMock(
    return_value={
      'fee_tier': {
        'maker_fee_rate': Decimal('0.001'),
        'taker_fee_rate': Decimal('0.002'),
      },
      **extra,
    }
  )
  monkeypatch.setattr(TransactionSummary, 'transaction_summary', request)
  market = PerpMarket(shared=shared(), product_id='BTC-PERP-INTX')
  with pytest.raises(NotImplementedError):
    await market.fees()


async def test_intx_inclusive_rates_are_not_taxed_twice(
  monkeypatch: pytest.MonkeyPatch,
):
  """Inclusive GST already belongs to the quoted maker/taker rates."""
  request = AsyncMock(
    return_value={
      'fee_tier': {'maker_fee_rate': Decimal(0), 'taker_fee_rate': Decimal('0.0003')},
      'goods_and_services_tax': {'rate': Decimal('0.09'), 'type': 'INCLUSIVE'},
    }
  )
  monkeypatch.setattr(TransactionSummary, 'transaction_summary', request)
  market = PerpMarket(shared=shared(), product_id='BTC-PERP-INTX')
  assert await market.fees() == Fees.symmetric(
    maker=Decimal(0), taker=Decimal('0.0003')
  )
  request.assert_awaited_once_with(
    product_type='FUTURE', contract_expiry_type='PERPETUAL', product_venue='INTX'
  )
