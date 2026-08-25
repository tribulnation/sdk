"""Lifecycle helpers for objects owning multiple async resources.

`AsyncResourceState` is the engine; `SDK` (see `core/invocations/sdk.py`) exposes it through
`resources()`/`__aenter__`/`__aexit__`.

Nothing here may be a dataclass. `dataclasses` refuses to mix frozen and non-frozen classes
in one hierarchy, so a dataclass field here would make frozen-ness contagious across every
SDK subclass -- which is exactly what used to force venue mixins into a single frozen-ness.
State therefore lives in `__dict__`, written directly so frozen instances can own it.
"""

from typing_extensions import Any, AsyncContextManager, Iterable
from dataclasses import dataclass
from contextlib import AsyncExitStack


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

  async def exit(self, exc_type, exc_value, traceback) -> bool | None:
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
