from typing_extensions import AsyncContextManager, Iterable
from dataclasses import dataclass

from tribulnation.sdk import SDK
from tribulnation.sdk.core import exception_wrapper

from typed_binance import Binance

wrap_exceptions = exception_wrapper()


@dataclass
class SdkMixin(SDK):
  client: Binance
  validate: bool = True

  @classmethod
  def new(
    cls,
    api_key: str | None = None,
    secret_key: str | None = None,
    *,
    validate: bool = True,
  ):
    client = Binance.new(api_key=api_key, secret_key=secret_key, validate=validate)
    return cls(client=client, validate=validate)

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    yield from super().resources()
    yield self.client
