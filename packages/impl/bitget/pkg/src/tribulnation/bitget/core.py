from typing_extensions import Any, AsyncContextManager, Iterable
from dataclasses import dataclass, field
import asyncio

from tribulnation.sdk import SDK
from tribulnation.sdk.core import exception_wrapper

from typed_bitget import Bitget
from typed_bitget.core import exc

wrap_exceptions = exception_wrapper()


@dataclass
class SdkMixin(SDK):
  client: Bitget
  uta: bool | None = None
  """Is this account in UTA mode? If None, it will be auto-detected on first use."""
  validate: bool = True
  _is_uta: bool | None = None
  _is_uta_lock: asyncio.Lock = field(
    default_factory=asyncio.Lock, init=False, repr=False
  )

  @SDK.method
  async def determine_uta(self) -> bool:
    try:
      await self.client.uta.account.info()
      return True
    except exc.AccountModeMismatch:
      return False

  async def is_uta(self) -> bool:
    if self.uta is not None:
      return self.uta
    elif self._is_uta is not None:  # short-circuit to avoid locking every time
      return self._is_uta
    else:
      async with self._is_uta_lock:
        if self._is_uta is None:
          self._is_uta = await self.determine_uta()
        return self._is_uta

  @classmethod
  def new(
    cls,
    access_key: str | None = None,
    secret_key: str | None = None,
    passphrase: str | None = None,
    *,
    validate: bool = True,
  ):
    client = Bitget.new(
      access_key=access_key, secret_key=secret_key, passphrase=passphrase
    )
    return cls(client=client, validate=validate)

  def resources(self) -> Iterable[AsyncContextManager[Any]]:
    yield from super().resources()
    yield self.client
