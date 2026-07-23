from typing_extensions import TYPE_CHECKING, Any, Awaitable, Callable, Protocol, TypeVar, cast
import asyncio
import functools
import inspect
import math
import random

if TYPE_CHECKING:
  from .context import Context

Fn = TypeVar('Fn', bound=Callable[..., Any])
RetryJitter = Callable[[float], float]


class Middleware(Protocol):
  def __call__(self, fn: Fn, ctx: 'Context') -> Fn:
    ...


def get_sdk_self(args: tuple[Any, ...]) -> Any | None:
  from .sdk import SDK
  if args and isinstance(args[0], SDK):
    return args[0]


def exclude_sdk_self(args: tuple[Any, ...]) -> tuple[Any, ...]:
  return args[1:] if get_sdk_self(args) is not None else args


def log(*, log_self: bool = False) -> Middleware:
  def bind(fn: Fn, ctx: 'Context') -> Fn:
    def write(args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
      path = ' -> '.join(ctx.path)
      log_args = args if log_self else exclude_sdk_self(args)
      print(f'Calling "{path}" with args: {log_args}, kwargs: {kwargs}')

    if inspect.isasyncgenfunction(fn):
      @functools.wraps(fn)
      async def asyncgen_wrapper(*args: Any, **kwargs: Any):
        write(args, kwargs)
        async for item in fn(*args, **kwargs):
          yield item

      return cast(Fn, asyncgen_wrapper)

    if inspect.iscoroutinefunction(fn):
      @functools.wraps(fn)
      async def coroutine_wrapper(*args: Any, **kwargs: Any) -> Any:
        write(args, kwargs)
        return await fn(*args, **kwargs)

      return cast(Fn, coroutine_wrapper)

    @functools.wraps(fn)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
      write(args, kwargs)
      return fn(*args, **kwargs)

    return cast(Fn, sync_wrapper)

  return bind


class RetryLogger(Protocol):
  def __call__(
    self,
    fn: Callable[..., Awaitable[Any]],
    ctx: 'Context',
    *,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    exception: Exception,
    retries: int,
    delay: float,
  ) -> None:
    ...


def default_retry_logger(
  fn: Callable[..., Awaitable[Any]],
  ctx: 'Context',
  *,
  args: tuple[Any, ...],
  kwargs: dict[str, Any],
  exception: Exception,
  retries: int,
  delay: float,
) -> None:
  path = '.'.join(ctx.path)
  print(f'Retry {retries} for {path} after {type(exception).__name__}; sleeping {delay:.2f}s')


def full_jitter(
  delay: float, *, random: Callable[[], float] = random.random,
) -> float:
  """Return a uniformly jittered delay between zero and the given delay."""
  return delay * random()


def retry(
  *exceptions: type[Exception],
  max_retries: int | None = None,
  base_delay: float = 1.0,
  max_delay: float | None = None,
  jitter: RetryJitter | None = full_jitter,
  log: RetryLogger | None = default_retry_logger,
) -> Middleware:
  handled = exceptions or (Exception,)

  def bind(fn: Fn, ctx: 'Context') -> Fn:
    if not inspect.iscoroutinefunction(fn):
      return fn

    @functools.wraps(fn)
    async def coroutine_wrapper(*args: Any, **kwargs: Any) -> Any:
      retries = 0
      while True:
        try:
          return await fn(*args, **kwargs)
        except handled as e:
          if max_retries is not None and retries >= max_retries:
            raise
          retries += 1
          delay = base_delay * 2**retries
          if max_delay is not None and delay > max_delay:
            delay = max_delay
          if jitter is not None:
            cap = delay
            delay = jitter(cap)
            if not math.isfinite(delay) or not 0 <= delay <= cap:
              raise ValueError(
                f'Retry jitter returned {delay!r}; expected a finite delay between 0 and {cap}',
              )
          if log is not None:
            log(fn, ctx, args=args, kwargs=kwargs, exception=e, retries=retries, delay=delay)
          await asyncio.sleep(delay)

    return cast(Fn, coroutine_wrapper)

  return bind
