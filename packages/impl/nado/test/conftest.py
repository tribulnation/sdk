"""A stand-in Nado client: every endpoint is an attribute a test replaces, so no test
opens a connection or needs credentials."""

from types import SimpleNamespace

import pytest
from typing_extensions import Any, cast
from typed_nado import Nado
from typed_nado.schemas import Symbol

from tribulnation.nado.core import Shared

X18 = 10**18
OWNER = '0x43103ea7d9aeb5724fdd98a18541cb81f00536f4'
SENDER = OWNER + '64656661756c740000000000'
"""The `default` subaccount of `OWNER`, as the venue spells it (lowercase)."""


def symbol(name: str, product_id: int, type: str = 'perp', **changes: object) -> Symbol:
  """A mainnet product as `symbols` sent it (2026-11-17), with `changes`."""
  row: dict[str, Any] = {
    'type': type,
    'product_id': product_id,
    'symbol': name,
    'price_increment_x18': X18,
    'size_increment': 50_000_000_000_000,
    'min_size': 100 * X18,
    'maker_fee_rate_x18': 100_000_000_000_000,
    'taker_fee_rate_x18': 350_000_000_000_000,
    'long_weight_initial_x18': 980_000_000_000_000_000,
    'long_weight_maintenance_x18': 990_000_000_000_000_000,
    'max_open_interest_x18': None,
    'trading_status': 'live',
    'isolated_only': False,
  }
  return cast(Symbol, {**row, **changes})


class Fake:
  """The client surfaces the adapter reads, as namespaces of replaceable endpoints."""

  def __init__(self, *, signer: bool = True):
    self.gateway: Any = SimpleNamespace()
    self.archive: Any = SimpleNamespace()
    self.archive_v2: Any = SimpleNamespace()
    self.streams: Any = SimpleNamespace()
    self.credentials: Any = (
      SimpleNamespace(sender=SENDER, owner=OWNER) if signer else None
    )


def shared_of(fake: Fake, *, sender: str | None = SENDER) -> Shared:
  """A shared owner over `fake`, with BTC-PERP (2), ETH-PERP (4) and KBTC (1) cached."""
  shared = Shared(client=cast(Nado, fake), sender=sender, owner=OWNER)
  shared.symbols.update(
    {
      'BTC-PERP': symbol('BTC-PERP', 2),
      'ETH-PERP': symbol('ETH-PERP', 4, price_increment_x18=X18 // 100),
      'KBTC': symbol('KBTC', 1, 'spot'),
    }
  )
  return shared


@pytest.fixture
def fake() -> Fake:
  """A client that signs."""
  return Fake()


@pytest.fixture
def shared(fake: Fake) -> Shared:
  """A shared owner over `fake`."""
  return shared_of(fake)
