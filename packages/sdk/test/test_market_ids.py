"""`QualifiedExchangeId` and `QualifiedMarketId` split the IDs `TradingMarkets` routes."""

import pytest

from tribulnation.sdk.market import QualifiedExchangeId, QualifiedMarketId


def test_market_id_splits_into_segments():
  """A market ID splits into account, exchange and market."""
  parsed = QualifiedMarketId.parse('dydx:perp:BTC-USD')
  assert parsed == QualifiedMarketId(
    account_id='dydx', exchange_id='perp', market_id='BTC-USD'
  )
  assert parsed.id == 'dydx:perp:BTC-USD'


def test_market_id_allows_empty_exchange():
  """The default exchange is an empty middle segment."""
  parsed = QualifiedMarketId.parse('hl::BTC')
  assert (parsed.account_id, parsed.exchange_id, parsed.market_id) == ('hl', '', 'BTC')
  assert parsed.exchange == QualifiedExchangeId(account_id='hl', exchange_id='')
  assert parsed.exchange.id == 'hl:'


def test_market_id_keeps_colons_in_market():
  """Everything after the second colon is the market ID."""
  parsed = QualifiedMarketId.parse('hl:spot:PURR/USDC:0')
  assert parsed.market_id == 'PURR/USDC:0'
  assert parsed.exchange.id == 'hl:spot'
  assert parsed.id == 'hl:spot:PURR/USDC:0'


@pytest.mark.parametrize('id', ['', 'hl', 'hl:spot', ':spot:BTC', 'hl:spot:', 'hl::'])
def test_malformed_market_id_raises(id: str):
  """A missing account or market segment is rejected with the expected format."""
  with pytest.raises(ValueError, match='<account_id>:<exchange_id>:<market_id>'):
    QualifiedMarketId.parse(id)


@pytest.mark.parametrize(
  'fields',
  [
    {'account_id': '', 'exchange_id': 'perp', 'market_id': 'BTC'},
    {'account_id': 'hl', 'exchange_id': 'perp', 'market_id': ''},
    {'account_id': 'h:l', 'exchange_id': 'perp', 'market_id': 'BTC'},
    {'account_id': 'hl', 'exchange_id': 'pe:rp', 'market_id': 'BTC'},
  ],
)
def test_malformed_market_fields_raise(fields: dict[str, str]):
  """Direct construction validates like `parse`."""
  with pytest.raises(ValueError, match='<account_id>:<exchange_id>:<market_id>'):
    QualifiedMarketId(**fields)


def test_exchange_id_splits_into_segments():
  """An exchange ID splits into account and exchange; the exchange may be empty."""
  assert QualifiedExchangeId.parse('dydx:perp') == QualifiedExchangeId(
    account_id='dydx', exchange_id='perp'
  )
  assert QualifiedExchangeId.parse('hl:').exchange_id == ''
  assert QualifiedExchangeId.parse('hl:spot').id == 'hl:spot'


@pytest.mark.parametrize('id', ['', 'hl', ':perp', 'hl:spot:BTC', 'hl::'])
def test_malformed_exchange_id_raises(id: str):
  """A missing account or extra segments are rejected with the expected format."""
  with pytest.raises(ValueError, match='"<account_id>:<exchange_id>", got'):
    QualifiedExchangeId.parse(id)
