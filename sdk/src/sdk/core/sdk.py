from typing_extensions import TypeVar, Callable, Coroutine, AsyncGenerator, Protocol

Fn = TypeVar('Fn', bound=Callable[..., Coroutine|AsyncGenerator])

class SDK(Protocol):
  __sdk_methods__: list[str] = []

  @classmethod
  def method(cls, fn: Fn) -> Fn:
    cls.__sdk_methods__.append(fn.__name__)
    return fn

S = TypeVar('S', bound=SDK)

def instrument(sdk: S, mapper: Callable[[Fn], Fn]) -> S:
  for attr in sdk.__sdk_methods__:
    wrapped = mapper(getattr(sdk, attr))
    setattr(sdk, attr, wrapped)
  return sdk