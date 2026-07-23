"""Lifecycle helpers for objects owning multiple async resources."""

from typing_extensions import Any, AsyncContextManager, Iterable
from dataclasses import dataclass, field
from contextlib import AsyncExitStack


@dataclass
class AsyncResourceState:
  """Mutable state for one declarative async resource owner."""
  stack: AsyncExitStack | None = None

  async def enter(self, resources: Iterable[AsyncContextManager[Any]]) -> None:
    """Enter resources in order and roll back partial acquisition."""
    if self.stack is not None:
      raise RuntimeError('Async resources are already active')
    stack = AsyncExitStack()
    await stack.__aenter__()
    try:
      for resource in resources:
        await stack.enter_async_context(resource)
    except BaseException:
      await stack.aclose()
      raise
    self.stack = stack

  async def exit(self, exc_type, exc_value, traceback) -> bool | None:
    """Exit all resources in reverse order."""
    if self.stack is None:
      raise RuntimeError('Async resources are not active')
    stack = self.stack
    self.stack = None
    return await stack.__aexit__(exc_type, exc_value, traceback)


@dataclass(frozen=True)
class AsyncResources:
  """Mixin for objects declaring async resources through ``resources``."""

  _resource_state: AsyncResourceState = field(
    default_factory=AsyncResourceState,
    init=False, repr=False, compare=False,
  )

  def resources(self) -> Iterable[AsyncContextManager[Any]]:
    """Return resources to enter, in dependency order."""
    raise NotImplementedError

  async def __aenter__(self):
    await self._resource_state.enter(self.resources())
    return self

  async def __aexit__(self, exc_type, exc_value, traceback) -> bool | None:
    return await self._resource_state.exit(exc_type, exc_value, traceback)
