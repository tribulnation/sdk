"""A surface combining two SDK mixins must still enter its client exactly once.

`Report` combines two surfaces that both borrow the same `Shared`. Overriding
`__aenter__` instead of `resources()` leaves two implementations in the MRO, exactly one
of which wins -- silently, discarding whatever the other owned. Nothing fails at the
call site, because clients connect lazily; the only symptom is a leaked socket per
instance, which no live check can see.
"""

from typing_extensions import Any, cast

from typed_coinbase import Coinbase

from tribulnation.coinbase import Report
from tribulnation.coinbase.core.mixin import Shared


class FakeClient:
  """A client counting how many times it is entered and exited."""

  def __init__(self):
    self.entered = 0
    self.exited = 0

  async def __aenter__(self):
    self.entered += 1
    return self

  async def __aexit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
    self.exited += 1


async def test_report_enters_its_shared_client_exactly_once() -> None:
  """History and snapshots name the same client, so it is entered and exited once."""
  client = FakeClient()
  async with Report(shared=Shared(client=cast(Coinbase, client))):
    assert client.entered == 1
  assert client.exited == 1
