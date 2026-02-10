from typing_extensions import TypeVar, Callable, Coroutine, AsyncGenerator, Protocol, Generic
from typing_extensions import _ProtocolMeta # type: ignore
from dataclasses import dataclass
import asyncio
import inspect

T = TypeVar('T')
AsyncFn = Callable[..., Coroutine|AsyncGenerator]
Fn = TypeVar('Fn', bound=AsyncFn)

@dataclass
class Method(Generic[Fn]):
  fn: Fn

  def __get__(self, instance: object, owner: type) -> Fn:
    return self.fn.__get__(instance, owner) # type: ignore

class SDKMeta(_ProtocolMeta):
  def __new__(cls, name, bases, dct):
    cls = super().__new__(cls, name, bases, dct)
    cls.__sdk_methods__ = {
      k for k, v in dct.items() if isinstance(v, Method)
    }
    for base in bases:
      if (methods := getattr(base, '__sdk_methods__', None)) is not None:
        cls.__sdk_methods__.update(methods)

    return cls

class SDK(Protocol, metaclass=SDKMeta):
  __sdk_methods__: set[str] = set()

  @classmethod
  def method(cls, fn: Fn) -> Fn:
    return Method(fn) # type: ignore

def instrument(sdk: T, *mappers: Callable[[Fn], Fn]) -> T:
  if (methods := getattr(sdk, '__sdk_methods__', None)) is not None:
    for attr in methods:
      if (fn := getattr(sdk, attr)) is not None:
        for mapper in mappers:
          fn = mapper(fn)
        setattr(sdk, attr, fn)
  for attr, value in list(sdk.__dict__.items()):
    if getattr(value, '__sdk_methods__', None) is not None:
      instrument(value, *mappers)
  return sdk

E = TypeVar('E', bound=Exception, contravariant=True)

class RetryLogger(Protocol, Generic[E]):
  def __call__(self, exception: E, *, retries: int, delay: float):
    ...
def default_retry_logger(exception: Exception, *, retries: int, delay: float):
  print(f'Exponential retry [{retries=}, {delay=:.2f}s]. Exception:', exception)

def exponential_retry(
  *exceptions: type[E],
  max_retries: int | None = None, base_delay: float = 1.0,
  max_delay: float | None = None, log: RetryLogger[E] | None = default_retry_logger
) -> Callable[[Fn], Fn]:
    def exponential_retry_wrapper(fn: Fn) -> Fn:
      if inspect.iscoroutinefunction(fn):
        async def exponential_retry_wrapped(*args, **kwargs):
          retries = 0
          while True:
            try:
              return await fn(*args, **kwargs)
            except exceptions as e:
              if max_retries is not None and retries >= max_retries:
                raise e
              retries += 1
              delay = base_delay * 2**retries
              if max_delay is not None and delay > max_delay:
                delay = max_delay
              if log is not None:
                log(e, retries=retries, delay=delay)
              await asyncio.sleep(delay)
        return exponential_retry_wrapped # type: ignore

      else:
        return fn

    return exponential_retry_wrapper

class Logger(Protocol):
  def __call__(self, function: AsyncFn, args: tuple, kwargs: dict):
    ...

def default_logger(function: AsyncFn, args: tuple, kwargs: dict):
  print(f'Calling {function.__name__} with {args=}, {kwargs=}')

def log(logger: Logger = default_logger) -> Callable[[Fn], Fn]:
  def log_wrapper(fn: Fn) -> Fn:
    if inspect.iscoroutinefunction(fn):
      async def coro_log_wrapped(*args, **kwargs):
        logger(fn, args, kwargs)
        return await fn(*args, **kwargs)
      return coro_log_wrapped # type: ignore

    elif inspect.isasyncgenfunction(fn):
      async def agen_log_wrapped(*args, **kwargs):
        logger(fn, args, kwargs)
        async for x in fn(*args, **kwargs):
          yield x
      return agen_log_wrapped # type: ignore

    elif inspect.isfunction(fn):
      def log_wrapped(*args, **kwargs):
        logger(fn, args, kwargs)
        return fn(*args, **kwargs)
      return log_wrapped # type: ignore

    else:
      raise ValueError(f"Unexpected function type: {type(fn)}")

  return log_wrapper