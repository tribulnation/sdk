from dataclasses import dataclass

from tribulnation.sdk.market.trade import Cancel as _Cancel

from mexc_sdk.core import MarketMixin

@dataclass
class Cancel(MarketMixin, _Cancel):
  async def order(self, id: str) -> _Cancel.Result:
    raise NotImplementedError('MEXC futures order cancelation is not implemented')
