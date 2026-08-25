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

    - `assets` is used for asset discovery in venues that don't support full enumeration (e.g. EVM blockchains). For others (e.g. CEXs) it's ignored"""
