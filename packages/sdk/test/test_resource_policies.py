"""Resource policies preserve ownership while keeping retries local to safe calls."""

import asyncio
from dataclasses import dataclass, field
from types import TracebackType
from typing_extensions import Any, AsyncContextManager, Callable, Iterable, TypeVar

import pytest
from typed_core import NetworkError as ClientNetworkError

from tribulnation.sdk import SDK
from tribulnation.sdk.core import (
  Context,
  ManagedResource,
  NetworkError,
  exception_wrapper,
  retry,
)

Fn = TypeVar('Fn', bound=Callable[..., Any])


def identity(fn: Fn) -> Fn:
  """Leave a resource operation unchanged."""
  return fn


@dataclass
class Client:
  """Record lifecycle calls and inject failures without network access."""

  enter_error: BaseException | None = None
  exit_error: BaseException | None = None
  suppress: bool = False
  entries: int = 0
  exits: int = 0
  received: BaseException | None = None

  async def __aenter__(self):
    """Record acquisition and optionally fail."""
    self.entries += 1
    if self.enter_error is not None:
      raise self.enter_error
    return self

  async def __aexit__(
    self,
    exc_type: type[BaseException] | None,
    exc_value: BaseException | None,
    traceback: TracebackType | None,
  ) -> bool:
    """Record cleanup and preserve or suppress the body exception."""
    self.exits += 1
    self.received = exc_value
    if self.exit_error is not None:
      raise self.exit_error
    return self.suppress


@dataclass
class Owner(SDK):
  """Own test resources through the production lifecycle."""

  owned: tuple[AsyncContextManager[object], ...]

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    """Declare resources in acquisition order."""
    yield from self.owned


def managed(client: Client) -> ManagedResource[Client]:
  """Translate client failures independently on entry and exit."""
  return ManagedResource(
    resource=client, wrap_enter=exception_wrapper(), wrap_exit=exception_wrapper()
  )


@pytest.mark.parametrize('phase', ['enter', 'exit'])
async def test_translation_without_whole_lifecycle_retries(phase: str):
  """Even a catch-all context must not replay acquisition or consumed cleanup."""
  original = ClientNetworkError('offline')
  client = Client()
  setattr(client, f'{phase}_error', original)
  with Context().retried(max_retries=2, base_delay=0).use():
    with pytest.raises(NetworkError) as caught:
      async with Owner((managed(client),)):
        pass
  assert caught.value.__cause__ is original
  assert client.entries == 1
  assert client.exits == (phase == 'exit')


async def test_partial_acquisition_rolls_back_and_owner_can_be_reused():
  """Translation does not bypass rollback or leave the owner's stack active."""
  first, second = Client(), Client(enter_error=ClientNetworkError('offline'))
  owner = Owner((managed(first), managed(second)))
  with pytest.raises(NetworkError):
    await owner.__aenter__()
  assert (first.entries, first.exits, second.exits) == (1, 1, 0)
  second.enter_error = None
  async with owner:
    pass
  assert (first.entries, first.exits, second.entries, second.exits) == (2, 2, 2, 1)


@pytest.mark.parametrize('suppress', [False, True])
async def test_body_error_is_not_translated_and_suppression_is_preserved(
  suppress: bool,
):
  """A venue error raised by user code is only passed to cleanup."""
  original = ClientNetworkError('user body')
  client = Client(suppress=suppress)
  try:
    async with Owner((managed(client),)):
      raise original
  except ClientNetworkError as error:
    assert not suppress
    assert error is original
  else:
    assert suppress
  assert client.received is original


@pytest.mark.parametrize('phase', ['enter', 'exit'])
@pytest.mark.parametrize(
  'error', [asyncio.CancelledError(), ValueError('unknown'), NetworkError('translated')]
)
async def test_unhandled_errors_keep_identity(phase: str, error: BaseException):
  """Cancellation, unknown errors and SDK errors pass through unchanged."""
  client = Client()
  setattr(client, f'{phase}_error', error)
  with pytest.raises(type(error)) as caught:
    async with Owner((managed(client),)):
      pass
  assert caught.value is error


async def test_duplicate_adapter_enters_once_and_returns_client():
  """Stable adapter identity retains resource de-duplication and entry results."""
  client = Client()
  adapter = managed(client)
  async with adapter as entered:
    assert entered is client
  async with Owner((adapter, adapter)):
    pass
  assert (client.entries, client.exits) == (2, 2)


async def test_entry_and_exit_policies_are_independent():
  """A venue can translate acquisition without applying that policy to cleanup."""
  original = ClientNetworkError('cleanup')
  client = Client(exit_error=original)
  adapter = ManagedResource(
    resource=client, wrap_enter=exception_wrapper(), wrap_exit=identity
  )
  with pytest.raises(ClientNetworkError) as caught:
    async with adapter:
      pass
  assert caught.value is original


async def test_decorated_calls_inside_lifecycle_keep_context_retries():
  """Only individual decorated calls retry; lifecycle spans are absent."""

  @dataclass
  class CallingClient(Client):
    """Make a retryable SDK call during both acquisition and cleanup."""

    attempts: dict[str, int] = field(default_factory=dict[str, int])
    paths: list[tuple[str, ...]] = field(default_factory=list[tuple[str, ...]])

    @SDK.method
    async def request(self, phase: str):
      """Fail the first request in each phase."""
      context = Context.current()
      assert context is not None
      self.paths.append(context.path)
      self.attempts[phase] = self.attempts.get(phase, 0) + 1
      if self.attempts[phase] == 1:
        raise NetworkError('retry this request')

    async def __aenter__(self):
      """Acquire once while retrying a safe request."""
      await super().__aenter__()
      await self.request('enter')
      return self

    async def __aexit__(
      self,
      exc_type: type[BaseException] | None,
      exc_value: BaseException | None,
      traceback: TracebackType | None,
    ) -> bool:
      """Clean up once while retrying a safe request."""
      await self.request('exit')
      return await super().__aexit__(exc_type, exc_value, traceback)

  client = CallingClient()
  context = Context(path=('outer',)).retried(NetworkError, max_retries=1, base_delay=0)
  with context.use():
    async with Owner((managed(client),)):
      assert Context.current() is context
  assert (client.entries, client.exits) == (1, 1)
  assert client.attempts == {'enter': 2, 'exit': 2}
  assert client.paths == [('outer', 'request')] * 4
  assert Context.current() is None


async def test_venue_entry_policy_retries_only_its_resource():
  """A verified-safe venue policy can retry entry without reacquiring predecessors."""

  class RetryableClient(Client):
    """Model a client that restores itself after its first failed acquisition."""

    async def __aenter__(self):
      """Fail once without retaining partial acquisition state."""
      await super().__aenter__()
      if self.entries == 1:
        raise ClientNetworkError('transient')
      return self

  def retry_entry(fn: Fn) -> Fn:
    """Explicitly apply retry outside translation for this resource only."""
    return retry(NetworkError, max_retries=1, base_delay=0)(
      exception_wrapper()(fn), Context()
    )

  first, second = Client(), RetryableClient()
  adapter = ManagedResource(
    resource=second, wrap_enter=retry_entry, wrap_exit=exception_wrapper()
  )
  async with Owner((managed(first), adapter)):
    pass
  assert (first.entries, first.exits) == (1, 1)
  assert (second.entries, second.exits) == (2, 1)
