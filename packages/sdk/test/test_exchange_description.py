"""Display metadata is distinct from the SDK exchange's opaque identity."""

from tribulnation.sdk.market import ExchangeDescription


def test_name_is_required_and_url_is_optional():
  """Names are always supplied; an unknown official landing page is omitted."""
  assert ExchangeDescription.__required_keys__ == {'id', 'type', 'name'}
  assert ExchangeDescription.__optional_keys__ == {'url'}
