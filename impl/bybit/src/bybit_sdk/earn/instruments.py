from datetime import timedelta
from decimal import Decimal
from typing_extensions import Collection, Iterable, Sequence

import httpx
import pydantic

from trading_sdk.core import ApiError, NetworkError, ValidationError
from trading_sdk.earn.instruments import Instrument, Instruments as _Instruments
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


class EasyEarnProductTagInfo(pydantic.BaseModel):
  model_config = {'extra': 'ignore'}
  display_on_country_code: str | None = None
  display_tag_key: str | None = None
  display_mode: int | None = None


class EasyEarnProduct(pydantic.BaseModel):
  model_config = {'extra': 'ignore'}
  product_id: str
  coin: int
  return_coin: int | None = None
  apy: str
  product_tag_info: EasyEarnProductTagInfo | None = None
  display_status: int | None = None
  tiered_apy_list: list[dict] = []
  tiered_non_reward_apy_e8: str | None = None
  interest_apy_e8: str | None = None
  product_type: int | None = None
  subscribe_start_at: str | None = None
  subscribe_end_at: str | None = None
  product_max_share: str | None = None
  total_deposit_share: str | None = None
  product_area: int | None = None
  staking_term: str | None = None
  is_fixed_term_loan_coin_product: bool | None = None
  is_display_countdown: bool | None = None
  is_vip: bool | None = None
  mega_drop_msg: str | None = None


class EasyEarnCoinProducts(pydantic.BaseModel):
  model_config = {'extra': 'ignore'}
  coin: int
  apy: str | None = None
  saving_products: list[EasyEarnProduct]


class EasyEarnProductsResult(pydantic.BaseModel):
  model_config = {'extra': 'ignore'}
  status_code: int
  coin_products: list[EasyEarnCoinProducts] = []
  total: int | None = None


class EasyEarnProductsResponse(pydantic.BaseModel):
  model_config = {'extra': 'ignore'}
  ret_code: int
  ret_msg: str | None = None
  result: EasyEarnProductsResult | None = None


def _parse_apr(value: str | None) -> Decimal:
  if not value:
    return Decimal('0')
  text = value.strip()
  if text.endswith('%'):
    text = text[:-1]
  if not text:
    return Decimal('0')
  return Decimal(text) / Decimal('100')


def _parse_duration(product: EasyEarnProduct) -> timedelta | None:
  if not product.staking_term:
    return None
  try:
    days = int(product.staking_term)
  except (TypeError, ValueError):
    return None
  if days <= 0:
    return None
  return timedelta(days=days)


def _parse_tags(product: EasyEarnProduct) -> list[Instrument.Tag]:
  tags: list[Instrument.Tag] = []
  if _parse_duration(product) is not None:
    tags.append('fixed')
  else:
    tags.append('flexible')
  tag_info = product.product_tag_info
  if tag_info and tag_info.display_tag_key:
    key = tag_info.display_tag_key.lower()
    if 'newuser' in key or 'new_user' in key:
      tags.append('new-users')
  return tags


def _parse_products(
  group: EasyEarnCoinProducts,
  *,
  symbol: str | None,
  url: str | None,
  coin_map: dict[int, str],
) -> Iterable[Instrument]:
  if not symbol:
    return []
  for product in group.saving_products:
    duration = _parse_duration(product)
    tags = _parse_tags(product)
    apr = _parse_apr(product.apy)
    yield_asset = None
    if product.return_coin is not None:
      yield_asset = coin_map.get(product.return_coin)
    yield Instrument(
      tags=tags,
      asset=symbol,
      apr=apr,
      yield_asset=yield_asset,
      min_qty=None,
      max_qty=None,
      duration=duration,
      url=url,
      id=product.product_id,
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


async def _fetch_easy_earn_products(client: httpx.AsyncClient, *, base: str) -> EasyEarnProductsResponse:
  data = await _fetch_json(
    client,
    f'{base}/x-api/s1/byfi/get-easy-earn-product-list',
    json_body={},
  )
  try:
    return EasyEarnProductsResponse.model_validate(data)
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
      products_resp = await _fetch_easy_earn_products(client, base=base)

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
    groups = products_resp.result.coin_products if products_resp.result else []
    for group in groups:
      symbol = coins.get(group.coin)
      for inst in _parse_products(group, symbol=symbol, url=earn_url, coin_map=coins):
        if assets is not None and inst.asset not in assets:
          continue
        if tags is not None and not any(t in tags for t in inst.tags):
          continue
        out.append(inst)
    return out
