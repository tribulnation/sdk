"""`levels` is an upper bound: Nado's REST snapshot is capped at 100 levels."""

from tribulnation.nado.market.books import MAX_LEVELS, venue_depth


def test_levels_above_100_request_100():
  """Above the venue's 100 levels the snapshot asks for 100 rather than failing."""
  assert MAX_LEVELS == 100
  assert venue_depth(None) == venue_depth(101) == venue_depth(10**6) == 100
  assert venue_depth(3) == 3
