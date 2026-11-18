"""`RequestBudget`: a burst, then one request per `every` seconds."""

from tribulnation.sdk.core import RequestBudget


def test_burst_then_one_per_period():
  """Five go out at once, the sixth waits; one token comes back every 20 seconds."""
  budget = RequestBudget(burst=5, every=20.0)
  assert [budget.take(0) for _ in range(6)] == [True] * 5 + [False]
  assert budget.take(10) is False
  assert budget.take(20) is True
  assert [budget.take(80) for _ in range(4)] == [True] * 3 + [False]


def test_tokens_never_exceed_the_burst():
  """An idle hour saves up `burst` tokens, no more."""
  budget = RequestBudget(burst=5, every=20.0)
  budget.take(0)
  assert [budget.take(3600) for _ in range(6)] == [True] * 5 + [False]
