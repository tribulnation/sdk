"""Support for earn integration tests."""

from collections.abc import Sequence
from dataclasses import dataclass

from tribulnation.sdk.earn.instruments import Instrument


@dataclass(frozen=True, kw_only=True)
class EarnResult:
  """Result of fetching one account's earn instruments."""

  instruments: Sequence[Instrument] | None = None
  failure: str | None = None
