"""IDs carry the account key they were opened under; `venue_id` stays the venue."""

# The stubs implement identity only; `concrete` clears the rest at runtime.
# pyright: reportAbstractUsage=false

from dataclasses import FrozenInstanceError, dataclass
from pathlib import Path
from typing_extensions import Sequence, TypeVar, get_args

import pytest

from tribulnation.sdk import MarketSDK
from tribulnation.sdk.impl import accounts
from tribulnation.sdk.impl.accounts import VenueId
from tribulnation.sdk.market import (
  Exchange,
  ExchangeDescription,
  Market,
  PerpExchange,
  PerpMarket,
  TradingVenue,
)


T = TypeVar('T', bound=type)


def concrete(cls: T) -> T:
  """Clear the abstract methods these tests never call."""
  cls.__abstractmethods__ = frozenset()
  return cls


@dataclass(frozen=True)
class Shared:
  """State a stub venue shares with its exchanges and markets, as real venues do."""

  account_id: str | None = None


@dataclass(frozen=True)
class StubMixin:
  """Identity shared by the stub venue, exchanges and markets."""

  shared: Shared

  @property
  def venue_id(self) -> VenueId:
    """The venue every stub object trades on."""
    return 'hyperliquid'

  @property
  def account_id(self) -> str:
    """The root SDK account key, else the venue ID."""
    return self.shared.account_id or self.venue_id


@concrete
@dataclass(frozen=True)
class StubMarket(StubMixin, Market):
  """A spot market that only reports its identity."""

  exchange: str
  symbol: str

  @property
  def exchange_id(self) -> str:
    """Exchange this market belongs to."""
    return self.exchange

  @property
  def market_id(self) -> str:
    """Native market ID."""
    return self.symbol


@concrete
@dataclass(frozen=True)
class StubPerpMarket(StubMarket, PerpMarket):
  """A perpetual market that only reports its identity."""


@concrete
@dataclass(frozen=True)
class StubExchange(StubMixin, Exchange):
  """A spot exchange creating stub markets."""

  name: str

  @property
  def exchange_id(self) -> str:
    """Exchange ID within the stub venue."""
    return self.name

  async def market(self, market_id: str, /) -> Market:
    """Create a stub spot market."""
    return StubMarket(self.shared, self.name, market_id)

  async def markets(self) -> Sequence[str]:
    """List the one stub market."""
    return ['BTC']


@concrete
@dataclass(frozen=True)
class StubPerpExchange(StubExchange, PerpExchange):
  """A perpetual exchange creating stub perpetual markets."""

  async def market(self, market_id: str, /) -> PerpMarket:
    """Create a stub perpetual market."""
    return StubPerpMarket(self.shared, self.name, market_id)


@dataclass(frozen=True)
class StubVenue(StubMixin, TradingVenue):
  """A venue with a `spot` and a `perp` exchange."""

  async def exchange(self, exchange_id: str, /) -> Exchange:
    """Create a stub exchange of the product family named by its ID."""
    if exchange_id == 'perp':
      return StubPerpExchange(self.shared, exchange_id)
    return StubExchange(self.shared, exchange_id)

  async def perp_exchange(self, exchange_id: str, /) -> PerpExchange:
    """Create a stub perpetual exchange."""
    return StubPerpExchange(self.shared, exchange_id)

  async def exchanges(self) -> Sequence[ExchangeDescription]:
    """List the stub exchanges."""
    return [
      {'id': 'spot', 'type': 'spot', 'name': 'Spot'},
      {'id': 'perp', 'type': 'perp', 'name': 'Perpetuals'},
    ]


@dataclass(frozen=True)
class StubSDK(MarketSDK):
  """A `MarketSDK` building stub venues for every account."""

  def _venue(self, id: str, /) -> TradingVenue:
    """Build a stub venue with the account key, like the real venue builders."""
    if id not in self.accounts:
      raise ValueError(f'No account found for venue id: {id}')
    return StubVenue(Shared(account_id=id))


@pytest.fixture
def sdk() -> StubSDK:
  """Two accounts on the same venue, neither keyed by it."""
  return StubSDK(
    {
      'main': accounts.Hyperliquid(public=True),
      'alt': accounts.Hyperliquid(public=True),
    }
  )


@pytest.mark.parametrize('market_id', ['main:spot:BTC', 'main:perp:BTC'])
async def test_market_ids_use_the_account_key_and_round_trip(
  sdk: StubSDK, market_id: str
):
  """The account key leads the ID, `venue_id` is the venue, and the ID resolves back."""
  market = await sdk.market(market_id)
  assert (market.id, market.account_id, market.venue_id) == (
    market_id,
    'main',
    'hyperliquid',
  )
  assert (await sdk.market(market.id)).id == market_id


async def test_perp_market_and_exchange_ids_round_trip(sdk: StubSDK):
  """Perpetual lookups carry the account key like spot ones."""
  market = await sdk.perp_market('main:perp:BTC')
  exchange = await sdk.perp_exchange('main:perp')
  assert (market.id, market.account_id) == ('main:perp:BTC', 'main')
  assert (exchange.id, exchange.account_id, exchange.venue_id) == (
    'main:perp',
    'main',
    'hyperliquid',
  )
  assert (await sdk.perp_market(market.id)).id == market.id
  assert (await sdk.perp_exchange(exchange.id)).id == exchange.id


@pytest.mark.parametrize('exchange_id', ['main:spot', 'main:perp'])
async def test_exchange_ids_round_trip(sdk: StubSDK, exchange_id: str):
  """Exchanges, and markets they create, carry the account key."""
  exchange = await sdk.exchange(exchange_id)
  assert (exchange.id, exchange.venue_id) == (exchange_id, 'hyperliquid')
  assert (await sdk.exchange(exchange.id)).id == exchange_id
  assert (await exchange.market('BTC')).id == f'{exchange_id}:BTC'


async def test_venue_reports_the_account_key(sdk: StubSDK):
  """A venue's `id` is its account key; its markets carry it."""
  venue = await sdk.venue('main')
  assert (venue.id, venue.account_id, venue.venue_id) == ('main', 'main', 'hyperliquid')
  assert (await venue.market('spot:BTC')).id == 'main:spot:BTC'
  assert (await venue.perp_market('perp:BTC')).id == 'main:perp:BTC'
  assert sdk.all['alt'].id == 'alt'


async def test_accounts_on_one_venue_have_distinct_ids(sdk: StubSDK):
  """Two accounts on the same venue do not collide."""
  main = await sdk.market('main:perp:BTC')
  alt = await sdk.market('alt:perp:BTC')
  assert (main.id, alt.id) == ('main:perp:BTC', 'alt:perp:BTC')
  assert main.venue_id == alt.venue_id == 'hyperliquid'


async def test_directly_built_venues_report_the_venue_id():
  """Outside a root SDK, the account key defaults to the venue ID."""
  venue = StubVenue(Shared())
  market = await venue.market('perp:BTC')
  assert (venue.id, market.id, market.account_id) == (
    'hyperliquid',
    'hyperliquid:perp:BTC',
    'hyperliquid',
  )
  keyed = StubVenue(Shared(account_id='mine'))
  assert (await keyed.market('perp:BTC')).id == 'mine:perp:BTC'


def test_identity_is_abstract():
  """Implementations must provide `venue_id` and `account_id` at every level."""
  for cls in (TradingVenue, Exchange, PerpExchange, Market, PerpMarket):
    assert {'venue_id', 'account_id'} <= cls.__abstractmethods__


async def test_default_account_keys_keep_their_ids():
  """Accounts keyed by their venue ID report the same IDs as before."""
  sdk = MarketSDK(
    {
      'coinbase': accounts.Coinbase(public=True),
      'binance': accounts.Binance(public=True),
    }
  )
  market = await sdk.market('coinbase:spot:BTC-USD')
  exchange = await sdk.perp_exchange('binance:usdm')
  assert (market.id, market.venue_id) == ('coinbase:spot:BTC-USD', 'coinbase')
  assert (exchange.id, exchange.venue_id) == ('binance:usdm', 'binance')


async def test_real_venue_reports_a_custom_account_key():
  """A real adapter's exchanges and markets carry a custom key."""
  sdk = MarketSDK(
    {'cb': accounts.Coinbase(public=True), 'cb2': accounts.Coinbase(public=True)}
  )
  market = await sdk.market('cb:spot:BTC-USD')
  other = await sdk.market('cb2:spot:BTC-USD')
  assert (market.id, market.account_id, market.venue_id) == (
    'cb:spot:BTC-USD',
    'cb',
    'coinbase',
  )
  assert other.id == 'cb2:spot:BTC-USD'
  assert (await sdk.market(market.id)).id == market.id


TRADING_ACCOUNTS: list[accounts.Account] = [
  accounts.Dydx(public=True),
  accounts.Dydx(venue='dydx_testnet', public=True),
  accounts.Hyperliquid(public=True),
  accounts.Hyperliquid(venue='hyperliquid_testnet', public=True),
  accounts.Aster(public=True),
  accounts.Aster(venue='aster_testnet', public=True),
  accounts.Lighter(public=True),
  accounts.Lighter(venue='lighter_testnet', public=True),
  accounts.Deribit(public=True),
  accounts.Mexc(public=True),
  accounts.Bit2Me(public=True),
  accounts.Bitget(public=True),
  accounts.Binance(public=True),
  accounts.Bybit(public=True),
  accounts.Coinbase(public=True),
  accounts.Kraken(public=True),
  accounts.Kucoin(public=True),
]
"""One public account per venue the Market SDK can build; Deribit testnet is refused."""


@pytest.mark.parametrize('account', TRADING_ACCOUNTS, ids=lambda a: a.venue)
async def test_every_venue_reports_its_account_venue(account: accounts.Account):
  """Each venue reports its account's `venue`, testnets included, and the account key."""
  venue = MarketSDK({'acct': account}).all['acct']
  assert (venue.id, venue.account_id, venue.venue_id) == ('acct', 'acct', account.venue)


def test_venue_ids_are_the_trading_accounts_venues():
  """`VenueId` lists exactly the trading accounts' venues, not the EVM chains."""
  trading = {
    venue
    for cls in accounts.VenueAccount.__subclasses__()
    for venue in get_args(cls.__dataclass_fields__['venue'].type)
  }
  assert trading == set(get_args(VenueId))
  assert {a.venue for a in TRADING_ACCOUNTS} == trading - {'deribit_testnet'}
  assert not issubclass(accounts.Evm, accounts.VenueAccount)


async def test_testnet_exchanges_and_markets_report_the_testnet_venue():
  """dYdX testnet exchanges and markets carry `'dydx_testnet'` and the account key."""
  from tribulnation.dydx.market import Exchange as DydxExchange, Market as DydxMarket

  sdk = MarketSDK({'t': accounts.Dydx(venue='dydx_testnet', public=True)})
  exchange = await sdk.all['t'].perp_exchange('perp')
  assert isinstance(exchange, DydxExchange)
  assert (exchange.id, exchange.venue_id) == ('t:perp', 'dydx_testnet')
  market = DydxMarket(shared=exchange.shared, perpetual_market={'ticker': 'ETH-USD'})  # type: ignore[typeddict-item]
  assert (market.id, market.account_id, market.venue_id) == (
    't:perp:ETH-USD',
    't',
    'dydx_testnet',
  )


def test_direct_testnet_construction_reports_the_testnet_venue():
  """Venues built directly for a testnet report it in their ID too."""
  from tribulnation.aster import AsterMarket
  from tribulnation.dydx import DydxMarket
  from tribulnation.hyperliquid import HyperliquidMarket
  from tribulnation.lighter import LighterMarket

  venues: list[TradingVenue] = [
    DydxMarket.new(public=True, mainnet=False),
    HyperliquidMarket.http(mainnet=False),
    AsterMarket.new(public=True, mainnet=False),
    LighterMarket.new(network='testnet', public=True),
  ]
  assert [(v.id, v.venue_id) for v in venues] == [
    ('dydx_testnet', 'dydx_testnet'),
    ('hyperliquid_testnet', 'hyperliquid_testnet'),
    ('aster_testnet', 'aster_testnet'),
    ('lighter_testnet', 'lighter_testnet'),
  ]


def test_accounts_are_frozen():
  """Account fields cannot be reassigned after construction."""
  account = accounts.Hyperliquid(public=True)
  with pytest.raises(FrozenInstanceError):
    account.venue = 'hyperliquid_testnet'  # type: ignore[misc]
  with pytest.raises(FrozenInstanceError):
    account.public = False  # type: ignore[misc]


def test_toml_accounts_load_frozen_with_testnet_venues(tmp_path: Path):
  """TOML loading still builds the accounts, testnet venues included."""
  path = tmp_path / 'sdk.toml'
  path.write_text(
    '[accounts.hl_test]\n'
    'venue = "hyperliquid_testnet"\n'
    'public = true\n'
    '[accounts.dydx_x]\n'
    'venue = "dydx"\n'
    'public = true\n'
    'address = "dydx1abc"\n'
  )
  loaded = accounts.load_accounts(path)
  assert {k: a.venue for k, a in loaded.items()} == {
    'hl_test': 'hyperliquid_testnet',
    'dydx_x': 'dydx',
  }
  sdk = MarketSDK(loaded)
  assert {k: (v.id, v.venue_id) for k, v in sdk.all.items()} == {
    'hl_test': ('hl_test', 'hyperliquid_testnet'),
    'dydx_x': ('dydx_x', 'dydx'),
  }
