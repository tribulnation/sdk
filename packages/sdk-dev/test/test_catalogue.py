"""Tests for catalogue coverage: key-form checks and the untranslated-ID diff, against a
synthetic catalogue.
"""

from tribulnation.catalogue import Catalogue

from sdk_dev.catalogue import Ids, check_keys, gap, market_key, platform_of


def catalogue() -> Catalogue:
  """A catalogue with one exchange, one index-keyed venue and one chain."""
  return Catalogue(
    assets={},
    platforms={},
    platforms_order=[],
    network_translations={'binance': {'ETH': 'ethereum', 'BSC': 'bnb-chain'}},
    asset_translations={
      'binance': {'BTC': 'bitcoin', 'USDT': 'tether'},
      'hyperliquid': {'0': 'usd-coin', '150': 'hyperliquid', 'HYPE': 'hyperliquid'},
      'ethereum': {'native': 'ethereum', '0x' + 'a' * 40: 'tether'},
    },
    spot_instruments={
      'binance': {'BTCUSDT': {'base': 'bitcoin', 'quote': 'tether'}},
      'hyperliquid': {
        'PURR/USDC:0': {'exchange': 'spot', 'base': 'purr', 'quote': 'usd-coin'}
      },
    },
    perpetual_instruments={
      'hyperliquid': {
        'BTC': {
          'exchange': '',
          'base': 'bitcoin',
          'quote': 'tether',
          'settlement': 'usd-coin',
        },
        'hyna:FARTCOIN': {
          'exchange': 'hyna',
          'base': 'fartcoin',
          'quote': 'tether',
          'settlement': 'ethena-usde',
        },
      }
    },
    debt_instruments={},
    pools={},
    spam={},
  )


def test_platform_of_maps_testnets_onto_mainnet():
  """Testnet accounts translate through the mainnet platform's tables."""
  assert platform_of('hyperliquid_testnet') == 'hyperliquid'
  assert platform_of('dydx') == 'dydx'


def test_check_keys_flags_keys_off_the_declared_form():
  """
  A name-keyed hyperliquid translation is the mistake the `[ids]` declaration exists to
  catch: the impl emits token indices, so `HYPE` would never match.
  """
  findings = check_keys(
    {'binance': 'symbol', 'hyperliquid': 'index', 'ethereum': 'address'}, catalogue()
  )
  assert [(f.venue, f.key) for f in findings] == [('hyperliquid', 'HYPE')]


def test_gap_lists_only_what_the_catalogue_lacks():
  """Translated IDs drop out; the rest come back sorted per category."""
  ids = Ids(
    assets={'BTC', 'USDT', 'PEPE'},
    networks={'ETH', 'TRX'},
    spot_markets={'BTCUSDT', 'ETHUSDT'},
  )
  missing = gap('binance', ids, catalogue())
  assert missing.assets == ['PEPE']
  assert missing.networks == ['TRX']
  assert missing.spot_markets == ['ETHUSDT']
  assert not missing.perp_markets and not missing.positions and not missing.empty


def test_gap_matches_instrument_keys_with_or_without_exchange_prefix():
  """
  Perpetual tables key non-default exchanges as `<exchange>:<market>` while spot tables
  key the bare market id, so both forms must match, and positions match either table.
  """
  ids = Ids(
    spot_markets={market_key('spot', 'PURR/USDC:0')},
    perp_markets={
      market_key('', 'BTC'),
      market_key('hyna', 'FARTCOIN'),
      market_key('xyz', 'SILVER'),
    },
    positions={'BTC', 'PURR/USDC:0', 'ETH'},
  )
  missing = gap('hyperliquid', ids, catalogue())
  assert missing.spot_markets == []
  assert missing.perp_markets == ['xyz:SILVER']
  assert missing.positions == ['ETH']


def test_gap_is_empty_when_everything_translates():
  """The all-clear case a finished venue should reach."""
  assert gap(
    'binance', Ids(assets={'BTC'}, spot_markets={'BTCUSDT'}), catalogue()
  ).empty
