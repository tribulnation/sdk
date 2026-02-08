from datetime import timedelta
from decimal import Decimal
from typing_extensions import Collection, Iterable, Sequence

import httpx
import pydantic

from tribulnation.sdk.core import ApiError, NetworkError, ValidationError
from tribulnation.sdk.earn.instruments import Instrument, Instruments as _Instruments
from bybit_sdk.core import SdkMixin, Platform

BYBIT_HEADERS_UA = (
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
  '(KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36'
)


def _platform_config(platform: Platform) -> tuple[str, str, dict]:
  if platform == 'bybit_eu':
    base = 'https://www.bybit.eu'
    earn_url = 'https://www.bybit.eu/en-EU/earn/home/'
  else:
    base = 'https://www.bybit.com'
    earn_url = 'https://www.bybit.com/en/earn'
  headers = {
    'accept': '*/*',
    'content-type': 'application/json',
    'origin': base,
    'referer': earn_url,
    'user-agent': BYBIT_HEADERS_UA,
  }
  return base, earn_url, headers


class ByfiCoin(pydantic.BaseModel):
  model_config = {'extra': 'ignore'}
  coin: list[str]


class ByfiCoinsResponseResult(pydantic.BaseModel):
  model_config = {'extra': 'ignore'}
  status_code: int
  coins: list[ByfiCoin]


class ByfiCoinsResponse(pydantic.BaseModel):
  model_config = {'extra': 'ignore'}
  ret_code: int
  ret_msg: str | None = None
  result: ByfiCoinsResponseResult | None = None


class ExploreProductInfo(pydantic.BaseModel):
  model_config = {'extra': 'ignore'}
  product_type: int
  apy_min_e8: str
  apy_max_e8: str
  duration_min_hour: int | None = None
  duration_max_hour: int | None = None
  value: str | None = None
  tiered_apy_list: list[dict] = []
  coin_x: int | None = None
  coin_y: int | None = None


class ExploreProtectedGroup(pydantic.BaseModel):
  model_config = {'extra': 'ignore'}
  apy_min_e8: str | None = None
  apy_max_e8: str | None = None
  product_infos: list[ExploreProductInfo]
  coin_enum: int


class ExploreProductsResult(pydantic.BaseModel):
  model_config = {'extra': 'ignore'}
  status_code: int
  protected_list: list[ExploreProtectedGroup] = []


class ExploreProductsResponse(pydantic.BaseModel):
  model_config = {'extra': 'ignore'}
  ret_code: int
  ret_msg: str | None = None
  result: ExploreProductsResult | None = None


def _parse_apr_e8(value: str | None) -> Decimal:
  if not value:
    return Decimal('0')
  return Decimal(value) / Decimal('100000000')


def _parse_duration(info: ExploreProductInfo) -> timedelta | None:
  min_h = info.duration_min_hour
  max_h = info.duration_max_hour
  if min_h is None or max_h is None:
    return None
  if min_h <= 0 or max_h <= 0:
    return None
  if min_h == max_h:
    return timedelta(hours=max_h)
  return None


def _parse_tags(info: ExploreProductInfo) -> list[Instrument.Tag]:
  duration = _parse_duration(info)
  if duration is not None:
    return ['fixed']
  return ['flexible']


def _parse_products(
  group: ExploreProtectedGroup,
  *,
  symbol: str | None,
  url: str | None,
) -> Iterable[Instrument]:
  if not symbol:
    return []
  for info in group.product_infos:
    duration = _parse_duration(info)
    tags = _parse_tags(info)
    apr = _parse_apr_e8(info.apy_max_e8)
    yield Instrument(
      tags=tags,
      asset=symbol,
      apr=apr,
      min_qty=None,
      max_qty=None,
      duration=duration,
      url=url,
    )


async def _fetch_json(client: httpx.AsyncClient, url: str, *, params=None, json_body=None) -> dict:
  try:
    r = await client.request('POST' if json_body is not None else 'GET', url, params=params, json=json_body)
    r.raise_for_status()
  except httpx.HTTPError as e:
    raise NetworkError(*e.args) from e
  return r.json()


async def _fetch_coins(client: httpx.AsyncClient, *, base: str) -> ByfiCoinsResponse:
  data = await _fetch_json(client, f'{base}/x-api/s1/byfi/get-coins')
  try:
    return ByfiCoinsResponse.model_validate(data)
  except pydantic.ValidationError as e:
    raise ValidationError(*e.args) from e


async def _fetch_explore_products(client: httpx.AsyncClient, *, base: str) -> ExploreProductsResponse:
  data = await _fetch_json(
    client,
    f'{base}/x-api/s1/byfi/get-explore-products',
    json_body={'match_user_asset': False, 'sort_apr': 0},
  )
  try:
    return ExploreProductsResponse.model_validate(data)
  except pydantic.ValidationError as e:
    raise ValidationError(*e.args) from e


class Instruments(SdkMixin, _Instruments):
  async def instruments(
    self, *, tags: Collection[Instrument.Tag] | None = None,
    assets: Sequence[str] | None = None,
  ) -> Sequence[Instrument]:
    base, earn_url, headers = _platform_config(self.platform)
    async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
      coins_resp = await _fetch_coins(client, base=base)
      products_resp = await _fetch_explore_products(client, base=base)

    if coins_resp.ret_code != 0:
      raise ApiError(f'Bybit API error: {coins_resp}')
    if products_resp.ret_code != 0:
      raise ApiError(f'Bybit API error: {products_resp}')

    coins = {}
    if coins_resp.result:
      for entry in coins_resp.result.coins:
        if len(entry.coin) >= 2:
          try:
            coin_id = int(entry.coin[0])
          except ValueError:
            continue
          coins[coin_id] = entry.coin[1]

    out: list[Instrument] = []
    groups = products_resp.result.protected_list if products_resp.result else []
    for group in groups:
      symbol = coins.get(group.coin_enum)
      for inst in _parse_products(group, symbol=symbol, url=earn_url):
        if assets is not None and inst.asset not in assets:
          continue
        if tags is not None and not any(t in tags for t in inst.tags):
          continue
        out.append(inst)
    return out
