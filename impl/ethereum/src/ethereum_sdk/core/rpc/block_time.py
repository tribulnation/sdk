from typing_extensions import Literal
from dataclasses import dataclass, field
from datetime import datetime
from .mixin import Mixin

def clamp(x: int, lo: int, hi: int) -> int:
  return max(lo, min(hi, x))

@dataclass
class BlockByTime(Mixin):
  block2time: dict[int, int] = field(default_factory=dict)

  async def cached_block_time(self, block_id: int) -> int:
    ts = self.block2time.get(block_id)
    if ts is None:
      block = await self.node.w3.eth.get_block(block_id)
      assert 'timestamp' in block
      ts = int(block['timestamp'])
      self.block2time[block_id] = ts
    return ts

  async def find_block_by_time(
    self, time: int | datetime, closest: Literal['before', 'after'], *,
    interpolation_after: int | None = 2, log: bool = False
  ) -> int:
    """Find the closest block to the given time.
    
    - `time`: target timestamp (seconds since epoch) or datetime
    - `closest`: when no block exists at the exact time, return the closest block before or after
    - `interpolation_after`: number of iterations before using interpolation (recommended: 2-3)
    - `log`: print debug information
    """
    t = int(time.timestamp()) if isinstance(time, datetime) else time
    async def rec(b0: int, b1: int, it: int) -> int:
      if log:
        print(f'[{it+1}] [{b0}, {b1}] ({b1-b0})')
      if b0 + 1 == b1:
        return b0 if closest == 'before' else b1
      t0 = await self.cached_block_time(b0)
      t1 = await self.cached_block_time(b1)
      if t <= t0:
        return b0
      if t1 <= t:
        return b1
      
      if t1 > t0 and interpolation_after is not None and it >= interpolation_after:
        block_span = b1 - b0
        time_span = t1 - t0
        est = b0 + int((t - t0) * block_span / time_span)
        b_mid = clamp(est, b0 + 1, b1 - 1)
      else:
        b_mid = (b0 + b1) // 2
        
      t_mid = await self.cached_block_time(b_mid)

      if closest == 'before':
        if t_mid <= t:
          return await rec(b_mid, b1, it+1)
        else:
          return await rec(b0, b_mid, it+1)
      else:  # closest == 'after'
        if t_mid < t:
          return await rec(b_mid, b1, it+1)
        else:
          return await rec(b0, b_mid, it+1)

    min_block = max([b for b, bt in self.block2time.items() if bt <= t], default=0)
    max_block = min([b for b, bt in self.block2time.items() if bt >= t], default=None)
    max_block = max_block or await self.node.w3.eth.block_number
    return await rec(min_block, max_block, 0)