"""Dynamic exchange names never replace Hyperliquid's native DEX IDs."""

from unittest.mock import AsyncMock

import pytest

from tribulnation.hyperliquid import HyperliquidMarket
from tribulnation.hyperliquid.market.impl.mixin import Shared


async def test_dynamic_full_names_preserve_empty_and_named_ids(
  monkeypatch: pytest.MonkeyPatch,
):
  """Use API display names and retain a native-name fallback for blank labels."""
  monkeypatch.setattr(
    Shared,
    'load_perp_dexs',
    AsyncMock(
      return_value={
        0: None,
        1: {'name': 'xyz', 'fullName': 'XYZ Exchange'},
        2: {'name': 'empty-label', 'fullName': ''},
      }
    ),
  )
  async with HyperliquidMarket.http() as sdk:
    assert await sdk.exchanges() == [
      {'id': 'spot', 'type': 'spot', 'name': 'Spot'},
      {'id': '', 'type': 'perp', 'name': 'Perpetuals'},
      {'id': 'xyz', 'type': 'perp', 'name': 'XYZ Exchange'},
      {'id': 'empty-label', 'type': 'perp', 'name': 'empty-label'},
    ]
