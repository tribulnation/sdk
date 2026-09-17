"""Lifecycle helpers for objects owning multiple async resources.

`AsyncResourceState` is the engine; `SDK` (see `core/invocations/sdk.py`) exposes it through
`resources()`/`__aenter__`/`__aexit__`.

SDK base classes must not carry dataclass lifecycle fields: Python refuses to mix
frozen and non-frozen dataclasses in one hierarchy. Mutable ownership state lives in
a separate object stored in `__dict__`, so both kinds of SDK subclass can own it.
"""

from typing_extensions import (
  Any,
  AsyncContextManager,
  Callable,
  Generic,
  Iterable,
  Protocol,
  ParamSpec,
  TypeVar,
)
from dataclasses import dataclass
from contextlib import AsyncExitStack
from types import TracebackType


T = TypeVar('T', covariant=True)
P = ParamSpec('P')
R = TypeVar('R')


class ResourceWrapper(Protocol):
  """A decorator preserving the resource method's signature."""

  def __call__(self, fn: Callable[P, R], /) -> Callable[P, R]:
    """Apply a venue policy to one lifecycle method."""
    ...


@dataclass(frozen=True, kw_only=True)
class ManagedResource(Generic[T]):
  """Delegate entry and cleanup through independent venue policies.

  Reuse the same adapter when declaring a resource more than once. Policies may
  translate exceptions or retry operations known to be safe; no retries are implicit.
  """

  resource: AsyncContextManager[T]
  wrap_enter: ResourceWrapper
  wrap_exit: ResourceWrapper

  async def __aenter__(self) -> T:
    """Enter the resource using its acquisition policy."""
    return await self.wrap_enter(self.resource.__aenter__)()

  async def __aexit__(
    self,
    exc_type: type[BaseException] | None,
    exc_value: BaseException | None,
    traceback: TracebackType | None,
  ) -> bool | None:
    """Apply cleanup policy and preserve the resource's suppression signal."""
    return await self.wrap_exit(self.resource.__aexit__)(exc_type, exc_value, traceback)


@dataclass
class AsyncResourceState:
  """Mutable state for one declarative async resource owner."""

  stack: AsyncExitStack | None = None

  async def enter(self, resources: Iterable[AsyncContextManager[Any]]) -> None:
    """Enter resources in order and roll back partial acquisition.

    Resources repeated within one `resources()` are entered once: composing with
    `yield from super().resources()` legitimately yields a shared client twice.
    """
    if self.stack is not None:
      raise RuntimeError(
        'Async resources are already active. Entering an owner also enters everything it '
        'exposes, so a child obtained from an entered parent is already live and must not '
        'be entered again.'
      )
    stack = AsyncExitStack()
    await stack.__aenter__()
    try:
      seen = set[int]()
      for resource in resources:
        # Identity, not equality: two equal-but-distinct clients are two resources.
        # `stack` holds each entered resource's `__aexit__`, so no id can be recycled.
        if id(resource) in seen:
          continue
        seen.add(id(resource))
        await stack.enter_async_context(resource)
    except BaseException:
      await stack.aclose()
      raise
    self.stack = stack

  async def exit(
    self,
    exc_type: type[BaseException] | None,
    exc_value: BaseException | None,
    traceback: TracebackType | None,
  ) -> bool | None:
    """Exit all resources in reverse order."""
    if self.stack is None:
      raise RuntimeError('Async resources are not active')
    stack = self.stack
    self.stack = None
    return await stack.__aexit__(exc_type, exc_value, traceback)


def resource_state(obj: object) -> AsyncResourceState:
  """Return `obj`'s resource state, creating it on first use.

  Writes straight into `__dict__`, bypassing `__setattr__`, so frozen dataclasses can own
  state without declaring a field -- the same mechanism `functools.cached_property` uses.
  """
  state = obj.__dict__.get('_resource_state')
  if state is None:
    state = obj.__dict__['_resource_state'] = AsyncResourceState()
  return state
