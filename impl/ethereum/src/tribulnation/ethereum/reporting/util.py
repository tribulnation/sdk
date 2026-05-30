
def source_id(service: str) -> str:
  from datetime import datetime, timezone
  from uuid import uuid4
  time = datetime.now(timezone.utc).isoformat()
  return f'{service}:{time}:{uuid4()}'