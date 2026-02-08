from typing_extensions import Sequence, Literal, Iterable
from datetime import timedelta
from decimal import Decimal
import pydantic
import httpx

from tribulnation.sdk.core import NetworkError, ValidationError, ApiError
from tribulnation.sdk.earn.instruments import Instrument, Instruments as _Instruments
from mexc_sdk.core import SdkMixin

MEXC_EARN_URL = 'https://www.mexc.com/earn'

class TieredSubsidyApr(pydantic.BaseModel):
  model_config = {'extra': 'forbid'}
  startQuantity: str
  endQuantity: Decimal | None
  apr: Decimal

class FinancialProduct(pydantic.BaseModel):
  model_config = {'extra': 'forbid'}
  financialId: str
  financialType: Literal['FLEXIBLE', 'FIXED', 'BLC_EARN']
  investPeriodType: Literal['FLEXIBLE', 'FIXED']
  fixedInvestPeriodType: int | None = None
  fixedInvestPeriodCount: int | None = None # days
  currencyId: str
  currency: str
  currencyIcon: str
  showApr: Decimal
  showAprMaxTip: bool = False
  subsidyTieredFlag: bool = False
  baseApr: Decimal
  subsidyApr: Decimal
  tieredSubsidyApr: list[TieredSubsidyApr] | None = None
  financialState: int
  startTime: int
  endTime: int | None
  soldOut: bool
  sort: int
  memberType: Literal['NORMAL', 'EFTD']
  """EFTD = New user"""
  profitCurrency: str | None = None
  profitCurrencyId: str | None = None
  profitCurrencyIcon: str | None = None
  minPledgeQuantity: Decimal
  perPledgeMaxQuantity: Decimal
  userPledgeQuantityFull: bool | None = None
  shareUrl: str | None = None


class CurrencyGroup(pydantic.BaseModel):
  model_config = {'extra': 'forbid'}
  currencyId: str
  currency: str
  currencyIcon: str
  minApr: str
  maxApr: str
  hasAprRange: bool = False
  investPeriodTypes: list[str]
  financialProductList: list[FinancialProduct]
  sort: int

class FinancialProductsResponse(pydantic.BaseModel):
  model_config = {'extra': 'forbid'}
  data: list[CurrencyGroup] 
  code: int = 0
  msg: str = ""
  timestamp: int = 0


def parse_tags(product: FinancialProduct) -> Iterable[Instrument.Tag]:
  if product.financialType == 'FIXED':
    yield 'fixed'
  else:
    yield 'flexible'
  if product.memberType == 'EFTD':
    yield 'new-users'

def parse_duration(product: FinancialProduct) -> timedelta | None:
  if product.fixedInvestPeriodCount is not None:
    return timedelta(days=product.fixedInvestPeriodCount)

def parse_group(group: CurrencyGroup) -> Iterable[Instrument]:
  for prod in group.financialProductList:
    if not prod.soldOut:
      tags = list(parse_tags(prod))
      duration = parse_duration(prod)
      apr = (prod.baseApr + prod.subsidyApr) / 100
      for tier in (prod.tieredSubsidyApr or []):
        if tier.apr:
          yield Instrument(
            asset=group.currency,
            apr=apr + tier.apr/100,
            yield_asset=prod.profitCurrency,
            min_qty=prod.minPledgeQuantity,
            max_qty=tier.endQuantity or prod.perPledgeMaxQuantity,
            tags=tags,
            duration=duration,
            url=prod.shareUrl or MEXC_EARN_URL,
          )
      yield Instrument(
        asset=group.currency,
        apr=apr,
        yield_asset=prod.profitCurrency,
        min_qty=prod.minPledgeQuantity,
        max_qty=prod.perPledgeMaxQuantity,
        tags=tags,
        duration=duration,
        url=prod.shareUrl or MEXC_EARN_URL,
      )

class Instruments(_Instruments, SdkMixin):
  async def instruments(
    self, *, tags: Sequence[Instrument.Tag] | None = None,
    assets: Sequence[str] | None = None,
  ) -> Sequence[Instrument]:
    
    async with httpx.AsyncClient() as client:
      r = await client.get('https://www.mexc.com/api/financialactivity/financial/products/list/V2')
    if r.status_code != 200:
      raise ApiError(f'MEXC API error: {r.status_code}')
    try:
      response: FinancialProductsResponse = FinancialProductsResponse.model_validate(r.json())
    except pydantic.ValidationError as e:
      raise ValidationError(*e.args) from e

    if response.code != 0:
      raise ApiError(f'MEXC API error: {response}')

    out: list[Instrument] = []
    for group in response.data:
      for instr in parse_group(group):
        if (assets is None or instr.asset in assets) and (tags is None or set(instr.tags).issubset(tags)):
          out.append(instr)
    return out