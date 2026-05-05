from tribulnation.sdk.core import SDK
from .instruments import Instruments

class Earn(Instruments):
  @SDK.method
  async def __aenter__(self):
    return self

  @SDK.method
  async def __aexit__(self, exc_type, exc_value, traceback):
    ...