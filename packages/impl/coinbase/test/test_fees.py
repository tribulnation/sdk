"""Unresolved account adjustments cannot be returned as combined fees."""

import pytest
from typed_coinbase import Coinbase

from tribulnation.coinbase.core.mixin import Shared
from tribulnation.coinbase.market import SpotMarket


def shared() -> Shared:
  """Build a credential-free fixture; no account request is made."""
  return Shared(client=Coinbase.new(public=True))


async def test_spot_does_not_claim_a_generic_tier_covers_stablepairs():
  """The global summary does not resolve per-product spot pricing."""
  market = SpotMarket(shared=shared(), product_id='USDC-USD')
  with pytest.raises(NotImplementedError, match='stablepair'):
    await market.fees()
