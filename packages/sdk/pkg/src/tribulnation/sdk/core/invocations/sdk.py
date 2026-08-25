from typing_extensions import (
  Any,
  AsyncContextManager,
  Callable,
  Iterable,
  ParamSpec,
  TypeVar,
  overload,
)
import functools
import inspect

from .context import Context
from ..lifecycle import resource_state

T = TypeVar('T', covariant=True)
Ps = ParamSpec('Ps')
Fn = TypeVar('Fn', bound=Callable[..., Any])


class Method:
  def __init__(self, name: str):
    self.name = name


def _decorate_method(
  fn: Fn,
  /,
  *,
  name: str | None = None,
) -> Fn:
  """Wrap `fn` so invoking it opens a child `Context` span and applies its middleware.

  Module-level rather than a `SDK` staticmethod so `SDK`'s own methods can use it inside
  the class body, where `SDK.method` does not exist yet.
  """
  name = name or fn.__name__

  def prepare():
    parent = Context.current()
    active = parent and parent.child(name)
    invoke = fn

    if active is None:
      return None, invoke

    for middleware in reversed(active.middleware):
      invoke = middleware(invoke, active)
    return active, invoke

  if inspect.isasyncgenfunction(fn):

    @functools.wraps(fn)
    async def asyncgen_wrapper(*args, **kwargs):
      active, invoke = prepare()
      if active is None:
        async for item in invoke(*args, **kwargs):
          yield item
        return
      token = Context.set_current(active)
      try:
        async for item in invoke(*args, **kwargs):
          yield item
      finally:
        Context.reset_current(token)

    wrapper = asyncgen_wrapper

  elif inspect.iscoroutinefunction(fn):

    @functools.wraps(fn)
    async def coroutine_wrapper(*args, **kwargs):
      active, invoke = prepare()
      if active is None:
        return await invoke(*args, **kwargs)
      token = Context.set_current(active)
      try:
        return await invoke(*args, **kwargs)
      finally:
        Context.reset_current(token)

    wrapper = coroutine_wrapper

  else:

    @functools.wraps(fn)
    def sync_wrapper(*args, **kwargs):
      active, invoke = prepare()
      if active is None:
        return invoke(*args, **kwargs)
      token = Context.set_current(active)
      try:
        return invoke(*args, **kwargs)
      finally:
        Context.reset_current(token)

    wrapper = sync_wrapper

  setattr(wrapper, '__sdk_method__', Method(name))
  return wrapper  # type: ignore[return-value]


class SDK:
  @overload
  @classmethod
  def method(cls, fn: Fn, /) -> Fn: ...

  @overload
  @classmethod
  def method(cls, /, *, name: str | None = None) -> Callable[[Fn], Fn]: ...

  @classmethod
  def method(
    cls,
    fn: Fn | None = None,
    /,
    *,
    name: str | None = None,
  ) -> Fn | Callable[[Fn], Fn]:
    if fn is None:
      return lambda fn: cls._decorate_method(fn, name=name)
    else:
      return cls._decorate_method(fn, name=name)

  _decorate_method = staticmethod(_decorate_method)

  def resources(self) -> Iterable[AsyncContextManager[Any]]:
    """Yield the async resources this object owns, in dependency order.

    A *data* method, deliberately: overrides compose with
    `yield from super().resources()`, so a class combining two SDK surfaces enters both
    their resources. Overriding `__aenter__` instead would silently discard one of them.

    Never decorate this with `@SDK.method`. It is a sync generator function, so the
    wrapper would open and close the `Context` span around generator *creation* rather
    than iteration, producing an empty span and hiding the body from middleware.
    """
    return ()

  @_decorate_method
  async def __aenter__(self):
    await resource_state(self).enter(self.resources())
    return self

  @_decorate_method
  async def __aexit__(self, exc_type, exc_value, traceback) -> bool | None:
    return await resource_state(self).exit(exc_type, exc_value, traceback)

  def __init_subclass__(cls, **kwargs: Any) -> None:
    super().__init_subclass__(**kwargs)
    inherited = set[str]()
    for base in cls.__mro__[1:]:
      for name, value in vars(base).items():
        if isinstance(getattr(value, '__sdk_method__', None), Method):
          inherited.add(name)

    for name in inherited:
      value = cls.__dict__.get(name)
      if value is not None and getattr(value, '__sdk_method__', None) is None:
        method = None
        for base in cls.__mro__[1:]:
          base_value = vars(base).get(name)
          method = getattr(base_value, '__sdk_method__', None)
          if isinstance(method, Method):
            break
        setattr(
          cls,
          name,
          _decorate_method(value, name=method.name if method is not None else name),
        )
