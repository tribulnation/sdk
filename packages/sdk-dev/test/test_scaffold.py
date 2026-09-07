"""Tests for the PoC notebook scaffold, against the real SDK surfaces it copies its
signatures from.
"""

from pathlib import Path

import json

import pytest

from sdk_dev.scaffold import (
  SURFACES,
  SurfaceMethod,
  call,
  imports_for,
  method_cell,
  surface_methods,
  surface_refs,
  write,
)


def by_name(surface: str, exchange: str = 'perp') -> dict[str, SurfaceMethod]:
  """The surface's methods, indexed by name."""
  refs = surface_refs(surface, exchange)  # type: ignore[arg-type]
  return {m.name: m for m in surface_methods(refs, skip=SURFACES[surface].skip)}


def test_surface_methods_read_the_abstract_signature():
  """The scaffold copies the interface as written, so the cell can't drift from it."""
  instruments = by_name('earn')['instruments']
  assert [p.name for p in instruments.parameters] == ['tags', 'assets']
  assert instruments.parameters[0].annotation == 'Collection[InstrumentTag] | None'
  assert instruments.returns == 'Sequence[Instrument]'
  assert instruments.kind == 'call'


def test_surface_methods_skip_sdk_plumbing_and_structural_methods():
  """`resources`/`method` come from the `SDK` base and `market` returns another SDK object."""
  market = by_name('market')
  assert not {'resources', 'method', 'market', 'id'} & set(market)
  assert {'depth', 'rules', 'index', 'next_funding', 'funding_rates'} <= set(market)
  assert 'index' not in by_name('market', 'spot')


def test_surface_methods_classify_how_a_result_is_consumed():
  """Streams are context managers, paginated methods are async iterables."""
  market = by_name('market')
  assert market['depth_stream'].kind == 'stream'
  assert market['funding_rates'].kind == 'pages'
  assert by_name('report')['history'].kind == 'pages'


def test_call_loops_over_markets_and_fills_required_arguments():
  """Every call is runnable as scaffolded, except for the placeholders it flags."""
  market = by_name('market')
  assert (
    call(market['depth'], 'MARKETS')
    == '{market_id: await depth(market_id) for market_id in MARKETS}'
  )
  assert call(market['funding_payments'], 'MARKETS') == (
    '{market_id: [record async for record in funding_payments(market_id, start, end)] '
    'for market_id in MARKETS}'
  )
  assert call(market['depth_stream'], 'MARKETS').startswith(
    'async with depth_stream(MARKETS[0]) as stream:'
  )
  assert call(by_name('earn')['instruments'], 'ASSETS') == 'await instruments()'


def test_method_cell_marks_mutating_calls_not_executed():
  """An order-placing cell is written but never run; the lint requires the marker."""
  cell = method_cell(by_name('market')['place_order'], 'MARKETS')
  assert cell.startswith(
    'async def place_order(market_id: str, /, order: Order, *, settings: Settings = {}) -> OrderResponse:'
  )
  assert '# not executed:' in cell
  assert '# not executed:' not in method_cell(by_name('market')['depth'], 'MARKETS')


def test_imports_resolve_names_to_their_modules():
  """
  Stdlib and typing names first, then the surface module, then the abstract classes'
  own modules (where `DepositMethod` lives), then the SDK core.
  """
  lines = imports_for(
    {
      'Decimal',
      'datetime',
      'timezone',
      'Sequence',
      'Book',
      'Settings',
      'OverflowPolicy',
    },
    SURFACES['market'],
  )
  assert lines[:2] == [
    'from datetime import datetime, timezone',
    'from decimal import Decimal',
  ]
  assert 'from typing_extensions import Sequence' in lines
  assert 'from tribulnation.sdk.market import Book, Settings' in lines
  assert 'from tribulnation.sdk.core import OverflowPolicy' in lines
  wallet = imports_for({'DepositMethod'}, SURFACES['wallet'], SURFACES['wallet'].refs)
  assert wallet == ['from tribulnation.sdk.wallet.deposit_methods import DepositMethod']


def test_write_creates_the_notebook_once(tmp_path: Path):
  """A second scaffold must not clobber a notebook someone has started filling in."""
  poc = tmp_path / 'poc'
  path = write(
    poc, 'venue', 'wallet', client_module='typed_venue', client_class='Venue'
  )
  assert path == poc / 'wallet.ipynb'

  cells: list[dict[str, str]] = [
    {'type': c['cell_type'], 'source': ''.join(c['source'])}
    for c in json.loads(path.read_text())['cells']
  ]
  code = [c['source'] for c in cells if c['type'] == 'code']
  assert 'from typed_venue import Venue' in code[0]
  assert 'client = Venue.new()' in code[0]
  assert "surface('typed_venue', 'Venue'" in code[1]
  assert code[2].startswith('async def deposit_methods(')
  assert code[3].startswith('async def withdrawal_methods(')
  coverage = next(c['source'] for c in cells if c['source'].startswith('## Coverage'))
  assert '| `deposit_methods` |' in coverage
  assert cells[-2]['source'].startswith('## Catalogue')
  assert "gap('venue', ids, load_catalogue())" in code[-1]
  assert 'deposit_methods()' in code[-1] and 'networks=' in code[-1]

  with pytest.raises(FileExistsError):
    write(poc, 'venue', 'wallet', client_module='typed_venue', client_class='Venue')
  nested = write(
    poc,
    'venue',
    'wallet',
    client_module='typed_venue',
    client_class='Venue',
    name='uta',
  )
  assert nested == poc / 'wallet' / 'uta.ipynb'
