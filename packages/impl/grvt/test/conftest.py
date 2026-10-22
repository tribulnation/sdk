"""A stand-in GRVT client: every endpoint is an attribute a test replaces, so no test
opens a connection or needs credentials."""

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from typing_extensions import Any, cast
from typed_grvt import Grvt
from typed_grvt.schemas import InstrumentDisplay

from tribulnation.grvt.core import Shared

BTC = 'BTC_USDT_Perp'
ETH = 'ETH_USDT_Perp'


def instrument(name: str, **changes: object) -> InstrumentDisplay:
  """A mainnet perpetual as `all_instruments` sent it (2026-10-22), with `changes`."""
  base = name.split('_')[0]
  row: InstrumentDisplay = {
    'instrument': name,
    'instrument_hash': '0x030501',
    'base': base,
    'quote': 'USDT',
    'kind': 'PERPETUAL',
    'venues': ['ORDERBOOK', 'RFQ'],
    'base_decimals': 9,
    'quote_decimals': 6,
    'tick_size': Decimal('0.1'),
    'min_size': Decimal('0.001'),
    'create_time': datetime(2024, 1, 1, tzinfo=timezone.utc),
    'max_position_size': Decimal('1000.0'),
    'funding_interval_hours': 8,
    'adjusted_funding_rate_cap': Decimal('0.3'),
    'min_notional': Decimal('100.0'),
    'status': 'ACTIVE',
  }
  return cast(InstrumentDisplay, {**row, **changes})


class Fake:
  """The client surfaces the adapter reads, as namespaces of replaceable endpoints."""

  def __init__(self, *, api_key: bool = True, private_key: bool = True):
    self.market: Any = SimpleNamespace()
    self.trading: Any = SimpleNamespace()
    self.market_streams: Any = SimpleNamespace()
    self.trading_streams: Any = SimpleNamespace()
    self.session: Any = object() if api_key else None
    self.trading_client: Any = SimpleNamespace(signer=object() if private_key else None)


def shared_of(fake: Fake, *instruments: InstrumentDisplay) -> Shared:
  """A shared owner over `fake`, with the given perpetuals already cached."""
  shared = Shared(client=cast(Grvt, fake))
  rows = instruments or (instrument(BTC), instrument(ETH, tick_size=Decimal('0.01')))
  shared.instruments.update((i['instrument'], i) for i in rows)
  return shared


@pytest.fixture
def fake() -> Fake:
  """A client with an API key and a private key."""
  return Fake()


@pytest.fixture
def shared(fake: Fake) -> Shared:
  """A shared owner over the fixture client, BTC and ETH cached."""
  return shared_of(fake)


@pytest.fixture
def make_fake() -> type[Fake]:
  """Build clients with other credentials: `make_fake(api_key=False)`."""
  return Fake


@pytest.fixture
def make_shared() -> Any:
  """Build a shared owner over another client or other perpetuals."""
  return shared_of


@pytest.fixture
def make_instrument() -> Any:
  """Build a perpetual row: `make_instrument('XAU_USDT_Perp', funding_interval_hours=4)`."""
  return instrument
