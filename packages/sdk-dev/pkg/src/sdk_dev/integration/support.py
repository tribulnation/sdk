"""Shared support for live SDK integration tests."""

from tribulnation.sdk import ApiError

from sdk_dev.narrow import is_mapping


def describe_exception(exception: Exception) -> str:
  """Describe an exception without exposing client or credential details."""
  if isinstance(exception, ApiError) and exception.args:
    payload: object = exception.args[0]
    if is_mapping(payload):
      code = payload.get('code')
      if isinstance(code, int) or (
        isinstance(code, str) and code.lstrip('-').isdigit()
      ):
        return f'API error {code}'
  causes: list[str] = []
  seen: set[int] = set()
  cause = exception.__cause__
  while cause is not None and id(cause) not in seen:
    seen.add(id(cause))
    name = type(cause).__name__
    if name != type(exception).__name__ and name not in causes:
      causes.append(name)
    cause = cause.__cause__
  if causes:
    return f'{type(exception).__name__} (caused by {" -> ".join(causes)})'
  # Transport/validation messages can contain signed URLs, keys or account rows.
  return type(exception).__name__
