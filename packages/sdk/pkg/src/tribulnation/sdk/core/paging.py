from dataclasses import dataclass
from typing_extensions import AsyncIterable, Sequence, TypeVar, Generic, Awaitable, Callable, ParamSpec
from functools import wraps

T = TypeVar('T')
U = TypeVar('U')
P = ParamSpec('P')

@dataclass
class PaginatedResponse(AsyncIterable[Sequence[T]], Awaitable[Sequence[T]], Generic[T]):
  stream: AsyncIterable[Sequence[T]]

  async def flatten(self) -> AsyncIterable[T]:
    async for page in self.stream:
      for item in page:
        yield item

  def __aiter__(self):
    return self.stream.__aiter__()

  async def sync(self) -> list[T]:
    out: list[T] = []
    async for page in self.stream:
      out.extend(page)
    return out

  def __await__(self):
    return self.sync().__await__()

  @classmethod
  def lift(cls, fn: Callable[P, AsyncIterable[Sequence[U]]]) -> 'Callable[P, PaginatedResponse[U]]':
    @wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> PaginatedResponse[U]:
      return cls(fn(*args, **kwargs)) # type: ignore
    return wrapper