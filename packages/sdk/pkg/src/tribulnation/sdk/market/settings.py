from typing_extensions import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
  from tribulnation.aster.market.settings import Settings as AsterSettings
  from tribulnation.bitget.market.impl.trading import BitgetSettings
  from tribulnation.dydx.market.impl.mixin import Settings as DydxSettings
  from tribulnation.extended.core import Settings as ExtendedSettings
  from tribulnation.grvt.market.common import Settings as GrvtSettings
  from tribulnation.hyperliquid.core.settings import Settings as HyperliquidSettings
  from tribulnation.kraken.market.impl.perp_account import KrakenSettings
  from tribulnation.lighter.market.common import Settings as LighterSettings
  from tribulnation.margin_trade.core import Settings as MarginTradeSettings
  from tribulnation.nado.core import Settings as NadoSettings

Settings = TypedDict(
  'Settings',
  {
    'aster': 'AsterSettings',
    'bitget': 'BitgetSettings',
    'dydx': 'DydxSettings',
    'extended': 'ExtendedSettings',
    'grvt': 'GrvtSettings',
    'hyperliquid': 'HyperliquidSettings',
    'kraken': 'KrakenSettings',
    'lighter': 'LighterSettings',
    'margin-trade': 'MarginTradeSettings',
    'nado': 'NadoSettings',
  },
  total=False,
)
"""Per-venue settings, keyed by venue implementation; each venue reads only its own key.
The functional form allows the hyphenated `margin-trade` key."""
