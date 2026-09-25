from typing_extensions import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
  from tribulnation.dydx.market.impl.mixin import Settings as DydxSettings
  from tribulnation.hyperliquid.core.settings import Settings as HyperliquidSettings
  from tribulnation.lighter.market.common import Settings as LighterSettings


class Settings(TypedDict, total=False):
  dydx: 'DydxSettings'
  hyperliquid: 'HyperliquidSettings'
  lighter: 'LighterSettings'
