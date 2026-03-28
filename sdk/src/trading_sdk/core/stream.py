from typing_extensions import AsyncIterable, Generic, TypeVar, Callable, Awaitable
from dataclasses import dataclass

T = TypeVar('T')

async def noop():
  ...

@dataclass
class Stream(AsyncIterable[T], Generic[T]):
  stream: AsyncIterable[T]
  unsubscribe: Callable[[], Awaitable] = noop

  def __aiter__(self):
    return self.stream.__aiter__()

  @classmethod
  def polled(cls, next: Callable[[], Awaitable[T]]) -> 'Stream[T]':
    stopped = False

    async def stream():
      nonlocal stopped
      while not stopped:
        yield await next()

    async def unsubscribe():
      nonlocal stopped
      stopped = True

    return cls(stream(), unsubscribe)
