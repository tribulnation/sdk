# %%
"""Diagnose Coinbase spot pagination with validated, read-only endpoint calls."""

import base64
from collections import Counter
from dataclasses import dataclass
from time import monotonic
from typing_extensions import Literal, TypedDict

from dotenv import load_dotenv
from typed_coinbase import Coinbase
from typed_coinbase.app.advanced_trade.http.products import Products
from typed_coinbase.app.advanced_trade.http.products.public import Public

load_dotenv()

Sort = Literal[
  'PRODUCTS_SORT_ORDER_VOLUME_24H_DESCENDING',
  'PRODUCTS_SORT_ORDER_LIST_TIME_DESCENDING',
]


class PageSummary(TypedDict):
  """Observable page boundaries and server pagination state."""

  rows: int
  reported_num_products: int
  has_next: bool | None
  cursor: str | None
  first: list[str]
  last: list[str]


@dataclass(frozen=True)
class Page:
  """Only public catalogue identifiers and pagination metadata."""

  ids: list[str]
  total: int
  cursor: str | None
  has_next: bool | None
  aliases: dict[str, list[str]]


def summarize_page(page: Page) -> PageSummary:
  """Describe boundaries with an explicit output schema."""
  return {
    'rows': len(page.ids),
    'reported_num_products': page.total,
    'has_next': page.has_next,
    'cursor': cursor_text(page.cursor),
    'first': page.ids[:2],
    'last': page.ids[-2:],
  }


async def fetch(
  endpoint: Products | Public,
  *,
  limit: int | None = None,
  cursor: str | None = None,
  offset: int | None = None,
  sort: Sort | None = None,
) -> Page:
  """Read one validated page, without exposing client credentials."""
  response = await endpoint.list(
    product_type='SPOT',
    limit=limit,
    cursor=cursor,
    offset=offset,
    products_sort_order=sort,
  )
  pagination = response.get('pagination') or {}
  return Page(
    ids=[p['product_id'] for p in response['products']],
    total=response['num_products'],
    cursor=pagination.get('next_cursor'),
    has_next=pagination.get('has_next'),
    aliases={p['product_id']: p.get('alias_to', []) for p in response['products']},
  )


def cursor_text(cursor: str | None) -> str | None:
  """Decode the server's public pagination token for diagnostics only."""
  if not cursor:
    return None
  return base64.b64decode(cursor + '=' * (-len(cursor) % 4)).decode(errors='replace')


async def sweep(
  endpoint: Products | Public, *, mode: Literal['cursor', 'offset'], sort: Sort | None
):
  """Bracket a bounded sweep with full snapshots and retain exact overlap evidence."""
  before = await fetch(endpoint, sort=sort)
  started = monotonic()
  pages: list[Page] = []
  cursor = None
  offset = 0
  for _ in range(20):
    page = await fetch(
      endpoint,
      limit=100,
      sort=sort,
      cursor=cursor,
      offset=offset if mode == 'offset' else None,
    )
    pages.append(page)
    if mode == 'cursor':
      if not page.cursor:
        break
      if page.cursor == cursor:
        raise RuntimeError('Repeated cursor')
      cursor = page.cursor
    else:
      if len(page.ids) < 100:
        break
      offset += 100
  else:
    raise RuntimeError('Sweep exceeded bounded page count')
  after = await fetch(endpoint, sort=sort)
  counts = Counter(pid for page in pages for pid in page.ids)
  baseline = set(before.ids) & set(after.ids)
  missing = sorted(baseline - counts.keys())
  duplicates = {
    pid: [i + 1 for i, page in enumerate(pages) if pid in page.ids]
    for pid, count in counts.items()
    if count > 1
  }
  print(
    {
      'mode': mode,
      'sort': sort,
      'seconds': round(monotonic() - started, 2),
      'baseline_counts': [len(before.ids), len(after.ids)],
      'baseline_set_changed': sorted(set(before.ids) ^ set(after.ids)),
      'baseline_order_positions_changed': sum(
        a != b for a, b in zip(before.ids, after.ids)
      ),
      'unique': len(counts),
      'missing': missing,
      'duplicates_pages': duplicates,
      'missing_aliases': {pid: before.aliases[pid] for pid in missing},
      'pages': [summarize_page(page) for page in pages],
    }
  )


async def investigate(*, public: bool):
  """Compare cursor/offset behavior independently on each endpoint."""
  async with Coinbase.new(public=public) as client:
    endpoint = (
      client.app.advanced_trade.http.products.public
      if public
      else client.app.advanced_trade.http.products
    )
    for mode in ('cursor', 'offset'):
      for sort in (None, 'PRODUCTS_SORT_ORDER_LIST_TIME_DESCENDING'):
        print({'public': public})
        await sweep(endpoint, mode=mode, sort=sort)


# %%
await investigate(public=True)

# %%
await investigate(public=False)


# %%
async def replay():
  """Replay identical public requests and compare explicit sort orders."""
  async with Coinbase.new(public=True) as client:
    endpoint = client.app.advanced_trade.http.products.public
    for sort in (
      None,
      'PRODUCTS_SORT_ORDER_VOLUME_24H_DESCENDING',
      'PRODUCTS_SORT_ORDER_LIST_TIME_DESCENDING',
    ):
      first = await fetch(endpoint, limit=100, sort=sort)
      second = await fetch(endpoint, limit=100, sort=sort, cursor=first.cursor)
      replayed = await fetch(endpoint, limit=100, sort=sort, cursor=first.cursor)
      repeated_first = await fetch(endpoint, limit=100, sort=sort)
      print(
        {
          'sort': sort,
          'first_ids': first.ids[:15],
          'cursor': cursor_text(first.cursor),
          'second_replay_same_order': second.ids == replayed.ids,
          'second_replay_changed_ids': sorted(set(second.ids) ^ set(replayed.ids)),
          'first_replay_same_order': first.ids == repeated_first.ids,
          'overlap_pages_1_2': sorted(set(first.ids) & set(second.ids)),
        }
      )


await replay()

# %% [markdown]
# Coverage: read-only spot product paging only. No SDK mapping, new IDs, or
# account mutations; catalogue translation and other market methods are out of scope.

# %%
import httpx
from unittest.mock import patch
from httpx._client import UseClientDefault
from httpx._types import AuthTypes

original_send = httpx.AsyncClient.send


async def inspect_send(
  self: httpx.AsyncClient,
  request: httpx.Request,
  *,
  stream: bool = False,
  auth: AuthTypes | UseClientDefault | None = httpx.USE_CLIENT_DEFAULT,
  follow_redirects: bool | UseClientDefault = httpx.USE_CLIENT_DEFAULT,
) -> httpx.Response:
  """Observe public query and cache metadata while leaving transport intact."""
  response = await original_send(
    self, request, stream=stream, auth=auth, follow_redirects=follow_redirects
  )
  print(
    {
      'query': str(request.url),
      'response_headers': {
        name: response.headers.get(name)
        for name in ('date', 'age', 'cache-control', 'cf-cache-status')
      },
    }
  )
  return response


async def inspect_sort():
  """Verify wire parameters and compare the first page under each sort."""
  async with Coinbase.new(public=True) as client:
    endpoint = client.app.advanced_trade.http.products.public
    with patch.object(httpx.AsyncClient, 'send', inspect_send):
      for sort in (
        'PRODUCTS_SORT_ORDER_VOLUME_24H_DESCENDING',
        'PRODUCTS_SORT_ORDER_LIST_TIME_DESCENDING',
      ):
        page = await endpoint.list(
          product_type='SPOT', limit=5, products_sort_order=sort
        )
        print(
          {
            'sort': sort,
            'products': [
              {'id': p['product_id'], 'new_at': str(p.get('new_at'))}
              for p in page['products']
            ],
          }
        )


await inspect_sort()


# %%
async def inspect_listing_times():
  """Check whether listing-time order agrees with returned listing timestamps."""
  async with Coinbase.new(public=True) as client:
    rows = (
      await client.app.advanced_trade.http.products.public.list(
        product_type='SPOT',
        products_sort_order='PRODUCTS_SORT_ORDER_LIST_TIME_DESCENDING',
      )
    )['products']
    dated = [(p['product_id'], p.get('new_at')) for p in rows]
    print(
      {
        'first_listing_times': [(pid, str(t)) for pid, t in dated[:5]],
        'later_rows_newer_than_first': sum(
          t > dated[0][1] for _, t in dated if t is not None and dated[0][1] is not None
        ),
      }
    )


await inspect_listing_times()


# %%
async def verify_full_response():
  """Check completion metadata on both default full-catalogue endpoints."""
  for public in (True, False):
    async with Coinbase.new(public=public) as client:
      endpoint = (
        client.app.advanced_trade.http.products.public
        if public
        else client.app.advanced_trade.http.products
      )
      page = await fetch(endpoint)
      print(
        {
          'public': public,
          'rows': len(page.ids),
          'unique': len(set(page.ids)),
          'has_next': page.has_next,
          'next_cursor': page.cursor,
          'reported_num_products': page.total,
        }
      )


await verify_full_response()
