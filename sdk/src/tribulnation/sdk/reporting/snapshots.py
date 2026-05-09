from typing_extensions import Sequence
from abc import abstractmethod

from tribulnation.sdk import SDK
from .models import Record

class Snapshots(SDK):
  @SDK.method
  @abstractmethod
  async def snapshots(self, assets: Sequence[str] | None = None) -> Record:
    """Fetch the current balances and positions of the account.
    
    - `assets` is used for asset discovery in venues that don't support full enumeration (e.g. EVM blockchains). For others (e.g. CEXs) it's ignored"""

  @SDK.method
  async def __aenter__(self):
    return self

  @SDK.method
  async def __aexit__(self, exc_type, exc_value, traceback):
    ...
