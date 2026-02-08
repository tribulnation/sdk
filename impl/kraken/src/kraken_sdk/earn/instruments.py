from typing_extensions import Sequence, Collection, AsyncIterable, Literal
from decimal import Decimal

import pydantic

from tribulnation.sdk.core import SDK, ApiError, ValidationError
from tribulnation.sdk.earn.instruments import Instrument, Instruments as _Instruments
from kraken_sdk.core import SdkMixin, wrap_exceptions

KRAKEN_EARN_URL = 'https://www.kraken.com/c/rewards'


class AprEstimate(pydantic.BaseModel):
  low: Decimal
  high: Decimal

class LockType(pydantic.BaseModel):
  type: Literal['flex', 'instant', 'bonded']

  def parse(self) -> Instrument.Tag:
    match self.type:
      case 'flex' | 'instant':
        return 'flexible'
      case 'bonded':
        return 'staking'

class EarnStrategyItem(pydantic.BaseModel):
  id: str
  asset: str
  apr_estimate: AprEstimate
  user_min_allocation: Decimal | None = None
  user_cap: Decimal | None = None
  can_allocate: bool = True
  can_deallocate: bool = True
  lock_type: LockType

class EarnStrategyResult(pydantic.BaseModel):
  items: list[EarnStrategyItem]
  next_cursor: str | None = None

class EarnStrategyResponse(pydantic.BaseModel):
  result: EarnStrategyResult
  error: list

class Instruments(SdkMixin, _Instruments):

  @SDK.method
  @wrap_exceptions
  async def _earn_strategies_page(self, cursor: str | None = None) -> EarnStrategyResponse:
    params = {} if cursor is None else {'cursor': cursor}
    r = await self.client.private_post_earn_strategies(params)
    try:
      return EarnStrategyResponse.model_validate(r)
    except pydantic.ValidationError as e:
      raise ValidationError(*e.args) from e

  async def _earn_strategies(self) -> AsyncIterable[EarnStrategyItem]:
    cursor = None
    while True:
      r = await self._earn_strategies_page(cursor)
      if r.error:
        raise ApiError(*r.error)
      for item in r.result.items:
        yield item
      if r.result.next_cursor is None:
        break
      else:
        cursor = r.result.next_cursor

  async def instruments(
    self,
    *,
    tags: Collection[Instrument.Tag] | None = None,
    assets: Sequence[str] | None = None,
  ) -> Sequence[Instrument]:
    r = await self.client.private_post_earn_strategies()
    out: list[Instrument] = []
    async for item in self._earn_strategies():
      out.append(Instrument(
        asset=item.asset,
        apr=(item.apr_estimate.low + item.apr_estimate.high) / 2 / 100,
        min_qty=item.user_min_allocation,
        max_qty=item.user_cap,
        tags=[item.lock_type.parse()],
        id=item.id,
        url=KRAKEN_EARN_URL,
      ))
    return out
