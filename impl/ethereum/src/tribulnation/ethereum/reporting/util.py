import functools

@functools.cache
def cached_etherscan(api_key: str | None = None, *, rate_limit: int | None, validate: bool = True):
  from etherscan import Etherscan
  return Etherscan.new(api_key=api_key, validate=validate, rate_limit=rate_limit)

def source_id(service: str) -> str:
  from datetime import datetime, timezone
  from uuid import uuid4
  time = datetime.now(timezone.utc).isoformat()
  return f'{service}:{time}:{uuid4()}'

class AutoDetect:
  ...

AUTO_DETECT = AutoDetect()