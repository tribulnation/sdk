from typing_extensions import AsyncIterable, TypeVar, ParamSpec, Generic, Sequence, Callable, Awaitable
from decimal import Decimal, ROUND_HALF_DOWN, ROUND_FLOOR

T = TypeVar('T')
U = TypeVar('U')
P = ParamSpec('P')

def round2tick(x: Decimal, tick_size: Decimal) -> Decimal:
  r = (x / tick_size).quantize(Decimal('1.'), rounding=ROUND_HALF_DOWN) * tick_size
  return r.normalize()

def trunc2tick(x: Decimal, tick_size: Decimal) -> Decimal:
  r = (x / tick_size).to_integral_value(rounding=ROUND_FLOOR) * tick_size
  return r.normalize()


class Stream(AsyncIterable[T], Awaitable[Sequence[T]], Generic[T]):
  def __init__(self, xs: AsyncIterable[T]):
    self.xs = xs

  def __aiter__(self):
    return self.xs.__aiter__()

  def __await__(self):
    async def coro():
      return [x async for x in self]
    return coro().__await__()

  @staticmethod
  def lift(fn: Callable[P, AsyncIterable[U]]):
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> Stream[U]:
      return Stream(fn(*args, **kwargs))
    return wrapper
  
class ChunkedStream(AsyncIterable[Sequence[T]], Awaitable[Sequence[T]], Generic[T]):
  def __init__(self, xs: AsyncIterable[Sequence[T]]):
    self.xs = xs

  def __aiter__(self):
    return self.xs.__aiter__()

  def __await__(self):
    async def coro():
      return [x async for xs in self for x in xs]
    return coro().__await__()

  async def flatten(self) -> AsyncIterable[T]:
    async for xs in self:
      for x in xs:
        yield x

  @staticmethod
  def lift(fn: Callable[P, AsyncIterable[Sequence[U]]]):
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> ChunkedStream[U]:
      return ChunkedStream(fn(*args, **kwargs))
    return wrapper