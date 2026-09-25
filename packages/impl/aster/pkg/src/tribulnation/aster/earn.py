"""Explicit Earn gap: no verified native instrument APR catalogue."""

from dataclasses import dataclass
from typing_extensions import Collection, Sequence
from tribulnation.sdk.earn import Earn as SDKEarn
from tribulnation.sdk.earn.instruments import Instrument, InstrumentTag
from .core import SharedMixin


@dataclass(frozen=True, kw_only=True)
class Earn(SharedMixin, SDKEarn):
  """Keep mainnet-only chain staking out of the unqualified Earn mapping."""

  async def instruments(
    self,
    *,
    tags: Collection[InstrumentTag] | None = None,
    assets: Collection[str] | None = None,
  ) -> Sequence[Instrument]:
    """Reject a fabricated Earn rate or catalogue."""
    raise NotImplementedError(
      'No verified Aster Earn catalogue or native instrument APR'
    )
