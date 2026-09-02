from typing_extensions import Collection
from abc import abstractmethod
import pydantic

from tribulnation.sdk import SDK
from .models import Provenance, Snapshot


class SnapshotRecord(pydantic.BaseModel):
  model_config = pydantic.ConfigDict(extra='forbid')
  snapshot: Snapshot
  provenance: Provenance


class Snapshots(SDK):
  @SDK.method
  @abstractmethod
  async def snapshot(self, assets: Collection[str] | None = None) -> SnapshotRecord:
    """Fetch the current balances and positions of the account.

    The record carries a `Provenance` tracing where it came from.

    Args:
      assets: Assets to look for, on venues that can't enumerate holdings themselves
        (EVM chains). Ignored where enumeration is native (CEXs).
    """
