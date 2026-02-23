from typing_extensions import TypeVar, Any, Callable, Protocol, Generic, Self, overload, Sequence
from abc import ABCMeta
from dataclasses import dataclass
import asyncio
import inspect

T = TypeVar('T')
Fn = TypeVar('Fn', bound=Callable)

@dataclass
class Method:
  name: str
  data: Any

  @staticmethod
  def get(fn) -> 'Method | None':
    return getattr(fn, '__sdk_method__', None)

class SDKMeta(ABCMeta):
  def __new__(cls: type, name: str, bases: tuple[type, ...], dct: dict[str, Any]):
    cls = ABCMeta.__new__(cls, name, bases, dct)
    cls.__sdk_methods__ = {}
    cls.__sdk_fields__ = {}
    for base in bases:
      if (methods := getattr(base, '__sdk_methods__', None)) is not None:
        cls.__sdk_methods__.update(methods)
      if (fields := getattr(base, '__sdk_fields__', None)) is not None:
        cls.__sdk_fields__.update(fields.items())
    for k, v in dct.items():
      if (method := Method.get(v)) is not None:
        cls.__sdk_methods__[k] = method
    for k, v in cls.__annotations__.items():
      if getattr(v, '__sdk_fields__', None) is not None:
        cls.__sdk_fields__[k] = v
    return cls


class Mapper(Protocol, Generic[Fn]):
  def __call__(self, fn: Fn, method: Method, path: Sequence[str]) -> Fn:
    ...

class SDK(metaclass=SDKMeta):
  __sdk_methods__: dict[str, Method] = {}
  __sdk_fields__: dict[str, type['SDK']] = {}

  def __sdk_instrument__(self, *mappers: Mapper[Fn], path: tuple[str, ...] = ()) -> Self:
    attrs = {}
    for method, data in self.__sdk_methods__.items():
      fn = getattr(self, method)
      for mapper in mappers:
        fn = mapper(fn, data, path)
      attrs[method] = fn
    for field in self.__sdk_fields__:
      sdk: SDK = getattr(self, field)
      attrs[field] = sdk.__sdk_instrument__(*mappers, path=path + (field,))

    if (fn := getattr(self, '__call__', None)) is not None:
      for mapper in mappers:
        fn = mapper(fn, data, path)
      attrs['__call__'] = fn

    sdk = self
    class Proxy:
      def __getattr__(self, name: str) -> Any:
        if name in attrs:
          return attrs[name]
        else:
          return sdk.__getattr__(name)

      def __setattr__(self, name: str, value: Any) -> None:
        self.sdk.__setattr__(name, value)

      def __call__(self, *args: Any, **kwargs: Any) -> Any:
        if '__call__' in attrs:
          return attrs['__call__'](*args, **kwargs)
        else:
          return sdk.__call__(*args, **kwargs)

      def __repr__(self) -> str:
        return sdk.__repr__()

    return Proxy() # type: ignore

  @classmethod
  def __sdk_hierarchy__(
    cls, *, field: str | None = None, indent: int = 0, prefix: str = "", last: bool = False
  ) -> str:
    # Prepare current line
    line = ""
    if indent > 0:
      # Show vertical line and branch
      line += prefix + ("└─ " if last else "├─ ")
    else:
      line += ""
    if field is not None:
      line += f"{field}: "
    line += cls.__name__ + "\n"

    # Prepare new prefix for children
    if indent > 0:
      child_prefix = prefix + ("   " if last else "│  ")
    else:
      child_prefix = ""

    # Print methods
    method_items = list(cls.__sdk_methods__.items())
    field_items = list(cls.__sdk_fields__.items())

    for i, (method, data) in enumerate(method_items):
      is_last = (i == len(method_items) - 1 and not field_items)
      mid_prefix = child_prefix + ("└─ " if is_last else "├─ ")
      line += mid_prefix + method + "()" + "\n"

    # Print fields
    for j, (next_field, sdk) in enumerate(field_items):
      is_last_field = (j == len(field_items) - 1)
      line += sdk.__sdk_hierarchy__(
        indent=indent + 1,
        field=next_field,
        prefix=child_prefix,
        last=is_last_field,
      )

    return line

  @overload
  @classmethod
  def method(cls, fn: Fn, /) -> Fn:
    ...
  @overload
  @classmethod
  def method(cls, /, *, name: str | None = None, data: Any = None) -> Callable[[Fn], Fn]:
    ...
  @classmethod
  def method(cls, fn = None, /, *, name: str | None = None, data: Any = None):
    def decorator(fn: Fn) -> Fn:
      setattr(fn, '__sdk_method__', Method(name=name or fn.__name__, data=data))
      return fn

    if fn is None:
      return decorator
    else:
      return decorator(fn)

S = TypeVar('S', bound=SDK)
def instrument(sdk: S, *mappers: Mapper[Fn]) -> S:
  return sdk.__sdk_instrument__(*mappers)

E = TypeVar('E', bound=Exception, contravariant=True)

class RetryLogger(Protocol, Generic[E]):
  def __call__(
    self, fn: Callable, method: Method, path: Sequence[str], *,
    args: tuple, kwargs: dict, exception: E, retries: int, delay: float
  ):
    ...

def default_retry_logger(
  fn: Callable, method: Method, path: Sequence[str], *,
  args: tuple, kwargs: dict, exception: Exception, retries: int, delay: float
):
  name = getattr(fn, '__name__', method.name)
  path_str = '.'.join(path)
  print(f'Exponential retry [{retries=}, {delay=:.2f}s]. Calling {path_str}.{name} with {args=}, {kwargs=}. Exception:', exception)

def exponential_retry(
  *exceptions: type[E],
  max_retries: int | None = None, base_delay: float = 1.0,
  max_delay: float | None = None, log: RetryLogger[E] | None = default_retry_logger
) -> Mapper:
    def exponential_retry_wrapper(fn: Fn, method: Method, path: Sequence[str]) -> Fn:
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
                log(fn, method, path, args=args, kwargs=kwargs, exception=e, retries=retries, delay=delay)
              await asyncio.sleep(delay)
        return exponential_retry_wrapped # type: ignore

      else:
        return fn

    return exponential_retry_wrapper

class Logger(Protocol):
  def __call__(
    self, fn: Callable, method: Method, path: Sequence[str], *,
    args: tuple, kwargs: dict
  ):
    ...

def default_logger(
  fn: Callable, method: Method, path: Sequence[str], *,
  args: tuple, kwargs: dict
):
  path_str = '.'.join(path)
  name = getattr(fn, '__name__', method.name)
  print(f'Calling {path_str}.{name} with {args=}, {kwargs=}')

def log(logger: Logger = default_logger) -> Mapper:
  def log_wrapper(fn: Fn, method: Method, path: Sequence[str]) -> Fn:
    if inspect.iscoroutinefunction(fn):
      async def coro_log_wrapped(*args, **kwargs):
        logger(fn, method, path, args=args, kwargs=kwargs)
        return await fn(*args, **kwargs)
      return coro_log_wrapped # type: ignore

    elif inspect.isasyncgenfunction(fn):
      async def agen_log_wrapped(*args, **kwargs):
        logger(fn, method, path, args=args, kwargs=kwargs)
        async for x in fn(*args, **kwargs):
          yield x
      return agen_log_wrapped # type: ignore

    elif inspect.isfunction(fn):
      def log_wrapped(*args, **kwargs):
        logger(fn, method, path, args=args, kwargs=kwargs)
        return fn(*args, **kwargs)
      return log_wrapped # type: ignore

    else:
      return fn

  return log_wrapper
