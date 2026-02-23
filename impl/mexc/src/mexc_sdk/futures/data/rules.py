from dataclasses import dataclass
from decimal import Decimal

from trading_sdk.market.data import Rules as _Rules

from mexc_sdk.core import PerpMixin, wrap_exceptions

@dataclass(frozen=True)
class Rules(PerpMixin, _Rules):
  @wrap_exceptions
  async def get(self) -> _Rules.Rules:
    info = self.info

    max_vol = Decimal(info['maxVol'])
    return _Rules.Rules(
      base=info['baseCoin'],
      quote=info['quoteCoin'],
      fee_asset=info.get('settleCoin') or info['quoteCoin'],
      tick_size=Decimal(info['priceUnit']),
      step_size=Decimal(info['volUnit']),
      fixed_min_qty=Decimal(info['minVol']),
      max_qty=max_vol if max_vol > 0 else None,
      maker_fee=Decimal(info['makerFeeRate']),
      taker_fee=Decimal(info['takerFeeRate']),
      api=True,
      details=info,
    )
