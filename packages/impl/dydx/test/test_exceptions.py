from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing_extensions import Any, cast

import pytest
from grpclib.const import Status
from grpclib.exceptions import GRPCError
from typed_core import exceptions as core
from typed_dydx.chain.feetiers import Feetiers
from typed_dydx.protos.dydxprotocol import feetiers as feetiers_proto

from tribulnation.dydx.core import wrap_exceptions
from tribulnation.dydx.core.exceptions import translate
from tribulnation.dydx.market.impl.fees import market_discount_params
from tribulnation.sdk.core import (
  ApiError,
  AuthError,
  BadRequest,
  Context,
  Error,
  LogicError,
  NetworkError,
  RateLimited,
  SDK,
  ValidationError,
)


def _underlying_error(status: int) -> core.ApiError:
  return core.ApiError(status, {'code': status, 'msg': 'request failed'})


async def test_wrap_exceptions_maps_http_429_to_rate_limited() -> None:
  source = _underlying_error(429)

  @wrap_exceptions
  async def fail() -> None:
    raise source

  with pytest.raises(RateLimited) as raised:
    await fail()

  assert raised.value.args == source.args
  assert raised.value.__cause__ is source


async def test_wrap_exceptions_keeps_other_api_errors_generic() -> None:
  source = _underlying_error(503)

  @wrap_exceptions
  async def fail() -> None:
    raise source

  with pytest.raises(ApiError) as raised:
    await fail()

  assert type(raised.value) is ApiError
  assert raised.value.args == source.args
  assert raised.value.__cause__ is source


def test_wrap_exceptions_maps_sync_http_429_to_rate_limited() -> None:
  @wrap_exceptions
  def fail() -> None:
    raise _underlying_error(429)

  with pytest.raises(RateLimited):
    fail()


async def test_wrap_exceptions_maps_async_generator_http_429_to_rate_limited() -> None:
  @wrap_exceptions
  async def fail() -> AsyncIterator[None]:
    if False:
      yield
    raise _underlying_error(429)

  with pytest.raises(RateLimited):
    await anext(fail())


async def test_external_context_retries_translated_rate_limit() -> None:
  class Retriable(SDK):
    def __init__(self) -> None:
      self.calls = 0

    @SDK.method
    @wrap_exceptions
    async def fetch(self) -> str:
      self.calls += 1
      if self.calls == 1:
        raise _underlying_error(429)
      return 'ok'

  target = Retriable()
  with Context().retried(RateLimited, max_retries=1, base_delay=0).use():
    assert await target.fetch() == 'ok'
  assert target.calls == 2


@pytest.mark.parametrize(
  ('source', 'expected'),
  [
    (core.NetworkError('offline'), NetworkError),
    (core.ValidationError('bad shape'), ValidationError),
    (core.BadRequest(400, 'not found'), BadRequest),
    (core.AuthError(401, 'denied'), AuthError),
    (core.RateLimited(429, 'slow down'), RateLimited),
    (core.ApiError(429, 'slow down'), RateLimited),
    (core.ApiError(500, 'boom'), ApiError),
    (core.LogicError('bug'), LogicError),
  ],
)
def test_translate_keeps_the_error_kind(source: core.Error, expected: type[Error]):
  """Each `typed_core` error becomes the SDK error of the same kind, with its args."""
  translated = translate(source)
  assert type(translated) is expected
  assert translated.args == source.args


@pytest.mark.parametrize(
  ('status', 'expected'),
  [
    (Status.NOT_FOUND, BadRequest),
    (Status.PERMISSION_DENIED, AuthError),
    (Status.RESOURCE_EXHAUSTED, RateLimited),
    (Status.UNAVAILABLE, NetworkError),
    (Status.INTERNAL, ApiError),
  ],
)
async def test_market_discount_params_grpc_errors_reach_the_sdk_translated(
  monkeypatch: pytest.MonkeyPatch, status: Status, expected: type[Error]
):
  """A gRPC status from the fee holiday query surfaces as the matching SDK error."""

  async def fail(*args: Any, **kwargs: Any) -> Any:
    raise GRPCError(status, 'failed')

  monkeypatch.setattr(feetiers_proto.QueryStub, 'all_market_fee_discount_params', fail)
  client = cast(Feetiers, SimpleNamespace(channel=None))
  with pytest.raises(expected) as raised:
    await wrap_exceptions(market_discount_params)(client)
  assert type(raised.value) is expected
