"""Shared support for live SDK integration tests."""

from tribulnation.sdk import ApiError


def describe_exception(exception: Exception) -> str:
  """Describe an exception without exposing client or credential details."""
  if isinstance(exception, ApiError) and exception.args:
    payload = exception.args[0]
    if isinstance(payload, dict):
      code = payload.get('code')
      message = payload.get('msg')
      if code is not None and message is not None:
        return f'API error {code}: {message}'
  if not exception.args:
    causes: list[str] = []
    cause = exception.__cause__
    while cause is not None:
      name = type(cause).__name__
      if name != type(exception).__name__ and name not in causes:
        causes.append(name)
      cause = cause.__cause__
    if causes:
      return f'{type(exception).__name__} (caused by {" -> ".join(causes)})'
    return f'{type(exception).__name__} (no details provided)'
  return f'{type(exception).__name__}: {exception}'
