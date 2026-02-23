from typing_extensions import Any
from dataclasses import dataclass

from trading_sdk.market.trade import Cancel as _Cancel

from mexc_sdk.core import PerpMixin

@dataclass(frozen=True)
class Cancel(PerpMixin, _Cancel):
  async def order(self, id: str) -> _Cancel.Result:
    raise NotImplementedError('MEXC futures do not allow API trading')

  async def open(self) -> Any:
    raise NotImplementedError('MEXC futures do not allow API trading')
