from typing_extensions import Any, Iterator, Callable, TypeVar, ParamSpec, Awaitable, overload
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
import inspect

from .middleware import Middleware, RetryJitter

T = TypeVar('T', covariant=True)
Ps = ParamSpec('Ps')

_current_ctx: ContextVar['Context | None'] = ContextVar('sdk_current_ctx', default=None)


@dataclass(frozen=True, kw_only=True)
class Context:
  middleware: tuple[Middleware, ...] = ()
  path: tuple[str, ...] = ()

  def child(self, name: str) -> 'Context':
    return replace(self, path=self.path + (name,))

  def add(self, middleware: Middleware) -> 'Context':
    return replace(self, middleware=self.middleware + (middleware,))

  def logged(self, *, log_self: bool = False) -> 'Context':
    from . import middleware
    return self.add(middleware.log(log_self=log_self))

  def retried(
    self,
    *exceptions: type[Exception],
    max_retries: int | None = None,
    base_delay: float = 1.0,
    max_delay: float | None = None,
    jitter: RetryJitter | None = None,
  ) -> 'Context':
    from . import middleware
    return self.add(middleware.retry(
      *exceptions,
      max_retries=max_retries,
      base_delay=base_delay,
      max_delay=max_delay,
      jitter=jitter,
    ))
  
  @overload
  async def call(self, fn: Callable[Ps, Awaitable[T]], *args: Ps.args, **kwargs: Ps.kwargs) -> T:
    ...

  @overload
  async def call(self, fn: Callable[Ps, T], *args: Ps.args, **kwargs: Ps.kwargs) -> T:
    ...

  async def call(self, fn: Callable[Ps, Any], *args: Ps.args, **kwargs: Ps.kwargs) -> Any:
    with self.use():
      result = fn(*args, **kwargs)
      if inspect.isawaitable(result):
        return await result
      return result

  @contextmanager
  def use(self) -> Iterator['Context']:
    token = Context.set_current(self)
    try:
      yield self
    finally:
      Context.reset_current(token)

  @staticmethod
  def current() -> 'Context | None':
    return _current_ctx.get()

  @staticmethod
  def set_current(ctx: 'Context | None'):
    return _current_ctx.set(ctx)

  @staticmethod
  def reset_current(token) -> None:
    _current_ctx.reset(token)
