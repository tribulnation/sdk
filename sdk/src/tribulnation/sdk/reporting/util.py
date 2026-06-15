from datetime import datetime, timezone
from uuid import uuid4

def source_id(service: str) -> str:
  time = datetime.now(timezone.utc).isoformat()
  return f'{service}:{time}:{uuid4()}'