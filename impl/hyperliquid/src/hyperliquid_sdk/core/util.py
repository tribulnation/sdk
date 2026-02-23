from typing_extensions import Generic, TypeVar, AsyncIterable
from dataclasses import dataclass
import asyncio

T = TypeVar('T')

@dataclass
class StreamManager(Generic[T]):
  listener: asyncio.Task
  subscribers: list[asyncio.Queue[T]]

  @classmethod
  def of(cls, stream: AsyncIterable[T]):
    subscribers: list[asyncio.Queue[T]] = []
    async def listener():
      async for msg in stream:
        for queue in subscribers:
          queue.put_nowait(msg)

    return cls(
      listener=asyncio.create_task(listener()),
      subscribers=subscribers,
    )

  async def close(self):
    if self.listener is not None:
      self.listener.cancel()

  async def subscribe(self) -> AsyncIterable[T]:
    queue = asyncio.Queue[T]()
    self.subscribers.append(queue)
    
    while True:
      # propagate exceptions raised in the listener
      task = asyncio.create_task(queue.get())
      await asyncio.wait([task, self.listener], return_when='FIRST_COMPLETED')
      if self.listener.done() and (exc := self.listener.exception()) is not None:
        raise exc
      yield await task