from typing_extensions import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
  from tribulnation.aster.market.settings import Settings as AsterSettings
  from tribulnation.dydx.market.impl.mixin import Settings as DydxSettings
  from tribulnation.extended.core import Settings as ExtendedSettings
  from tribulnation.hyperliquid.core.settings import Settings as HyperliquidSettings
  from tribulnation.lighter.market.common import Settings as LighterSettings
  from tribulnation.margin_trade.core import Settings as MarginTradeSettings

Settings = TypedDict(
  'Settings',
  {
    'aster': 'AsterSettings',
    'dydx': 'DydxSettings',
    'extended': 'ExtendedSettings',
    'hyperliquid': 'HyperliquidSettings',
    'lighter': 'LighterSettings',
    'margin-trade': 'MarginTradeSettings',
  },
  total=False,
)
"""Per-venue settings, keyed by venue implementation; each venue reads only its own key.
The functional form allows the hyphenated `margin-trade` key."""
