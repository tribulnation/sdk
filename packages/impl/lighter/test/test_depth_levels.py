"""`levels` is an upper bound: Lighter caps it at the source's shape, never refusing."""

from tribulnation.lighter.market.books import cap_levels


def test_levels_above_a_source_shape_are_capped():
  """The full book keeps any `levels`; the BBO serves one level whatever is asked."""
  assert cap_levels('order_book', 10**6) == 10**6
  assert cap_levels('bbo', 10**6) == 1
  assert cap_levels('bbo', None) == 1
