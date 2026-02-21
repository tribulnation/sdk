from typing_extensions import Sequence, Any
from dataclasses import dataclass

from trading_sdk.core import ApiError
from trading_sdk.market.trade import Cancel as _Cancel
from hyperliquid.exchange.cancel import Cancel as CancelType
from hyperliquid_sdk.perps.core import PerpMixin

@dataclass(frozen=True)
class Cancel(PerpMixin, _Cancel):
  async def orders(self, ids: Sequence[str]) -> Any:
    asset = self.asset_id
    cancels: list[CancelType] = [
      {'a': asset, 'o': int(id)}
      for id in ids
    ]
    result = await self.client.exchange.cancel(*cancels)
    if result['status'] != 'ok':
      raise ApiError(result)
    else:
      out: list[_Cancel.Result] = []
      errors: dict[str, str] = {}
      for i, s in enumerate(result['response']['data']['statuses']):
        if s == 'success':
          out.append(_Cancel.Result(details={'status': 'success', 'id': ids[i]}))
        elif isinstance(s, dict) and (err := s.get('error')) is not None:
          errors[ids[i]] = err
        else:
          errors[ids[i]] = f'Unknown status: {s}'
      if errors:
        raise ApiError(errors)
      return out

  async def order(self, id: str) -> _Cancel.Result:
    return (await self.orders([id]))[0]


  async def open(self) -> Any:
    orders = await self.client.info.open_orders(self.address, dex=self.dex)
    return await self.orders([str(o['oid']) for o in orders if o['coin'] == self.asset_name])