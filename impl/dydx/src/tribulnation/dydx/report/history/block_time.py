from typing_extensions import Protocol
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


class BlockTimeCache(Protocol):
  def get(self, height: int) -> datetime | None:
    ...
  def set(self, height: int, time: datetime):
    ...


@dataclass
class MemoryBlockTimeCache(BlockTimeCache):
  cache: dict[int, datetime] = field(default_factory=dict)

  def get(self, height: int) -> datetime | None:
    return self.cache.get(height)

  def set(self, height: int, time: datetime):
    self.cache[height] = time


@dataclass
class FilesBlockTimeCache(BlockTimeCache):
  path: Path
  cache: dict[int, datetime] = field(default_factory=dict)

  @classmethod
  def at(cls, root: Path | str):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    cache: dict[int, datetime] = {}
    for path in root.glob('*'):
      if path.is_file():
        height = int(path.stem)
        cache[height] = datetime.fromisoformat(path.read_text())
    return cls(root, cache)

  def set(self, height: int, time: datetime):
    self.cache[height] = time
    (self.path / str(height)).write_text(time.isoformat())

  def get(self, height: int) -> datetime | None:
    return self.cache.get(height)