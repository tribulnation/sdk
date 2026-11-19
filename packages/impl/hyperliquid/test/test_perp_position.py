"""Perpetual positions from `clearinghouseState`, liquidation price included."""

from decimal import Decimal

from typing_extensions import Any, cast
from typed_hyperliquid.info.clearinghouse_state import ClearinghouseState

from tribulnation.hyperliquid.market.impl.perps_position import parse_position
from tribulnation.sdk.market import PerpPosition


def entry(
  coin: str,
  *,
  szi: str,
  entry_px: str,
  liquidation_px: str | None,
  leverage: dict[str, Any],
) -> dict[str, Any]:
  """One `assetPositions` entry, as the venue writes it."""
  return {
    'type': 'oneWay',
    'position': {
      'coin': coin,
      'szi': szi,
      'leverage': leverage,
      'entryPx': entry_px,
      'positionValue': '1000',
      'unrealizedPnl': '0',
      'returnOnEquity': '0',
      'liquidationPx': liquidation_px,
      'marginUsed': '100',
      'maxLeverage': 10,
      'cumFunding': {'allTime': '0', 'sinceOpen': '0', 'sinceChange': '0'},
    },
  }


CROSS_20: dict[str, Any] = {'type': 'cross', 'value': 20}
ISOLATED_10: dict[str, Any] = {
  'type': 'isolated',
  'value': 10,
  'rawUsd': '-15987.720707',
}

XYZ_STATE = cast(
  ClearinghouseState,
  {
    'assetPositions': [
      entry(
        'xyz:TSLA',
        szi='7.0',
        entry_px='389.077',
        liquidation_px=None,
        leverage=CROSS_20,
      ),
      entry(
        'xyz:GOLD',
        szi='-0.4',
        entry_px='3714.07',
        liquidation_px='133942.6839044118',
        leverage=CROSS_20,
      ),
      entry(
        'xyz:HOOD',
        szi='250.0',
        entry_px='71.083',
        liquidation_px='67.3167187663',
        leverage=ISOLATED_10,
      ),
    ],
    'crossMaintenanceMarginUsed': '1956.85065',
    'withdrawable': '0.0',
    'time': 1795077438667,
  },
)
"""A public account's `xyz` builder-dex state (mainnet, 2026-11-19), as raw strings: a
cross long the venue names no liquidation price for, a cross short and an isolated long."""


def test_builder_dex_positions_carry_the_liquidation_price():
  """An isolated builder-dex position reports the venue's `liquidationPx`."""
  assert parse_position(XYZ_STATE, 'xyz:HOOD') == PerpPosition(
    size=Decimal('250.0'),
    entry_price=Decimal('71.083'),
    liquidation_price=Decimal('67.3167187663'),
  )
  assert parse_position(XYZ_STATE, 'xyz:GOLD').liquidation_price == Decimal(
    '133942.6839044118'
  )


def test_null_liquidation_price_is_none():
  """A `null` `liquidationPx` (collateral covers the position) is `None`."""
  assert parse_position(XYZ_STATE, 'xyz:TSLA') == PerpPosition(
    size=Decimal('7.0'), entry_price=Decimal('389.077'), liquidation_price=None
  )


def test_unlisted_coin_is_flat():
  """A coin the state does not list is a flat position with no liquidation price."""
  assert parse_position(XYZ_STATE, 'xyz:NVDA') == PerpPosition()
  assert parse_position(XYZ_STATE, 'HOOD') == PerpPosition()


def test_validated_decimals_parse_alike():
  """Validated responses hold `Decimal`s instead of strings; the result is the same."""
  validated = cast(
    ClearinghouseState,
    {
      'assetPositions': [
        entry(
          'BTC',
          szi='-0.01',
          entry_px='91000',
          liquidation_px=None,
          leverage=CROSS_20,
        )
      ]
    },
  )
  pos = validated['assetPositions'][0]['position']
  pos['szi'], pos['entryPx'] = Decimal('-0.01'), Decimal('91000')
  pos['liquidationPx'] = Decimal('98500.5')
  assert parse_position(validated, 'BTC') == PerpPosition(
    size=Decimal('-0.01'),
    entry_price=Decimal('91000'),
    liquidation_price=Decimal('98500.5'),
  )
