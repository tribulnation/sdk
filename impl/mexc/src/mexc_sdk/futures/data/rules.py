from dataclasses import dataclass

from trading_sdk.market.data import Rules as _Rules

from mexc_sdk.core import MarketMixin

@dataclass
class Rules(MarketMixin, _Rules):
  async def get(self) -> _Rules.Rules:
    raise NotImplementedError('MEXC futures rules are not implemented')
