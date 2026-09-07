"""Tests for the static walk of a typed client's endpoint surface, against a synthetic
client package shaped like the generated ones.
"""

from pathlib import Path

import pytest

from sdk_dev.surface import (
  ClientLookupError,
  Method,
  Parameter,
  load_client,
  methods,
  render,
  signature,
)

CLIENT = {
  '__init__.py': '',
  'main.py': '''
from functools import cached_property
from .core.base import Base
from .spot import Spot
from .streams import Streams


class Venue(Base):
  """Root."""

  @cached_property
  def spot(self) -> Spot:
    """Spot REST."""
    return Spot(client=self.client)

  @cached_property
  def streams(self) -> Streams:
    """WebSocket."""
    return Streams.new(self.client)
''',
  'core/__init__.py': '',
  'core/base.py': '''
class Base:
  client: object

  @classmethod
  def new(cls, *, public: bool = False) -> 'Base':
    """Build a client."""
    return cls()

  async def request(self, path: str) -> object:
    """Send a request."""
    return None
''',
  'spot/__init__.py': '''
from functools import cached_property
from .ticker import Ticker
from .orderbook import Orderbook
from .account import Account


class Spot(Ticker, Orderbook):
  """Spot namespace."""

  @cached_property
  def account(self) -> Account:
    """Account."""
    return Account(client=self.client)
''',
  'spot/ticker.py': '''
from typing_extensions import Literal, TypedDict
from ..core.base import Base


class TickerRow(TypedDict):
  price: str


Response = list[TickerRow]


class Ticker(Base):
  async def ticker(
    self, symbol: str, *, kind: Literal['spot', 'perp'] = 'spot', validate: bool | None = None
  ) -> Response:
    """Get one symbol's ticker, public.

    Args:
      symbol: The symbol.
    """
    return await self.request('/ticker')
''',
  'spot/orderbook.py': '''
from ..core.base import Base


class Orderbook(Base):
  async def orderbook(self, symbol: str, /, limit: int | None = None) -> dict[str, str]:
    """Get the order book."""
    return {}
''',
  'spot/account.py': '''
from decimal import Decimal
from ..core.base import Base


class Account(Base):
  async def balances(self) -> dict[str, Decimal]:
    """List balances, private."""
    return {}
''',
  'streams/__init__.py': '''
from ..core.base import Base


class Streams(Base):
  """Streams."""

  @classmethod
  def new(cls, client: object) -> 'Streams':
    return cls()

  def trades(self, symbol: str):
    """Subscribe to trades."""
    return None
''',
}


@pytest.fixture
def client_root(tmp_path: Path) -> Path:
  """Write the synthetic `typed_venue` package and return its search path."""
  for relative, source in CLIENT.items():
    path = tmp_path / 'typed_venue' / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)
  return tmp_path


def paths(client_root: Path) -> dict[str, Method]:
  """Walk the synthetic client and index its methods by path."""
  _, cls = load_client('typed_venue', search_paths=[client_root])
  return {m.path: m for m in methods(cls, 'typed_venue')}


def test_walk_follows_property_namespaces_and_mixins(client_root: Path):
  """
  Endpoints come from two places: `cached_property` namespaces that return the next
  class down, and mixins whose methods a namespace class inherits. Both are walked,
  and the path records the namespace route, not the defining class.
  """
  found = paths(client_root)
  assert set(found) == {
    'spot.ticker',
    'spot.orderbook',
    'spot.account.balances',
    'streams.trades',
  }


def test_walk_leaves_out_core_plumbing(client_root: Path):
  """`request`, `new` and the like come from the client's `core` and are not endpoints."""
  found = paths(client_root)
  assert not any(p.endswith(('request', 'new')) for p in found)


def test_method_drops_validate_and_expands_response_alias(client_root: Path):
  """
  The per-call `validate` override is noise in a listing, and `Response` says nothing
  until the module-level alias it names is expanded.
  """
  ticker = paths(client_root)['spot.ticker']
  assert [p.name for p in ticker.parameters] == ['symbol', 'kind']
  assert ticker.returns == 'list[TickerRow]'
  assert ticker.summary == "Get one symbol's ticker, public."


def test_load_client_needs_a_single_root_class(client_root: Path):
  """Without `main` defining exactly one class the root has to be named explicitly."""
  with pytest.raises(ClientLookupError):
    load_client('typed_missing', search_paths=[client_root])
  _, cls = load_client('typed_venue', 'Spot', search_paths=[client_root])
  assert cls.name == 'Spot'


@pytest.mark.parametrize(
  ('parameters', 'returns', 'expected'),
  [
    ([], None, '()'),
    (
      [
        Parameter('symbol', 'positional-only', 'str', None),
        Parameter('limit', 'positional or keyword', 'int | None', 'None'),
      ],
      'Book',
      '(symbol: str, /, limit: int | None = None) -> Book',
    ),
    (
      [
        Parameter('symbol', 'positional or keyword', 'str', None),
        Parameter('kind', 'keyword-only', "Literal['a']", "'a'"),
      ],
      None,
      "(symbol: str, *, kind: Literal['a'] = 'a')",
    ),
    (
      [
        Parameter('args', 'variadic positional', None, None),
        Parameter('kw', 'keyword-only', 'int', None),
      ],
      None,
      '(*args, kw: int)',
    ),
    ([Parameter('only', 'positional-only', 'str', None)], None, '(only: str, /)'),
  ],
)
def test_signature_renders_every_parameter_kind(
  parameters: list[Parameter], returns: str | None, expected: str
):
  """The `/` and `*` separators land where Python puts them."""
  assert signature(parameters, returns) == expected


def test_render_filters_by_namespace_and_regex(client_root: Path):
  """`paths` narrows to a namespace subtree; `grep` matches path or summary."""
  found = list(paths(client_root).values())
  assert (
    render(found, paths=['spot.account'])
    .splitlines()[0]
    .startswith('spot.account.balances(')
  )
  assert 'spot.ticker' in render(found, grep='public')
  assert 'spot.orderbook' not in render(found, grep='public')
  assert render(found, grep='nothing-matches') == ''
