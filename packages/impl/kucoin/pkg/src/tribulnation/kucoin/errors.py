"""KuCoin result codes: which mean a refused order, a missing order or throttling.

References:
  - [KuCoin error codes](https://www.kucoin.com/docs-new/error-code)
"""

from collections.abc import Mapping
from datetime import timedelta
from typing_extensions import cast

from tribulnation.sdk.core import ApiError, Error, RateLimited

AMBIGUOUS_CODES = frozenset({'500000', '408000', '429000'})
"""Internal error, gateway timeout and throttling: the order may or may not have been
accepted, so a placement answered with one is never `OrderRejected`."""
AUTH_CODES = frozenset(
  {'400001', '400002', '400003', '400004', '400005', '400006', '400007', '411100'}
)
"""Key, signature, timestamp, passphrase, IP or account rejections: never an order's fault."""
POSITION_LIMIT_CODES = frozenset({'126042'})
"""`126042` "Exceeded maximum position limit"."""
NOT_FOUND_CODES = frozenset({'100001', '100004', '126043', 'order_not_exist'})
"""Answers to a cancel or query that the order is gone: futures `100001`
(`error.getOrder.orderNotExist`) and `100004` ("Order is in not cancelable state", the
order already finished), spot `126043` ("Order does not exist")."""
NOT_FOUND_MESSAGES = (
  'order not exist',
  'order_not_exist',
  'the order does not exist',
  'order does not exist',
)
"""Lower-case messages KuCoin sends with the generic `400100` for a missing spot order."""


def payload_of(exc: BaseException) -> Mapping[str, object] | None:
  """The KuCoin envelope (`{code, msg}`) a typed error carries, if any.

  Envelope errors are raised as `(code, msg, envelope)`; HTTP-status errors as
  `(status, body)` with the decoded JSON body.
  """
  for arg in exc.args:
    if isinstance(arg, Mapping) and 'code' in arg:
      return cast(Mapping[str, object], arg)


def error_code(exc: BaseException) -> str | None:
  """The native result code of a KuCoin error, as a string, if it carries one."""
  if (payload := payload_of(exc)) is not None:
    return str(payload['code'])


def error_message(exc: BaseException) -> str:
  """The native message of a KuCoin error, lower-cased; empty when it has none."""
  payload = payload_of(exc)
  return str(payload.get('msg', '')).lower() if payload is not None else ''


def refused(exc: Error) -> bool:
  """Whether a placement error is KuCoin definitively refusing the order.

  Any native result code is a refusal except the ambiguous ones (`AMBIGUOUS_CODES`) and
  credential failures; an error without a code (network failures, 5xx pages) is not,
  nor is anything answered with a 5xx status.
  """
  code = error_code(exc)
  status = exc.args[0] if exc.args and isinstance(exc.args[0], int) else None
  return (
    isinstance(exc, ApiError)
    and not isinstance(exc, RateLimited)
    and (status is None or status < 500)
    and code is not None
    and code not in AMBIGUOUS_CODES
    and code not in AUTH_CODES
  )


def not_found(exc: Error) -> bool:
  """Whether a cancel or query error says the order does not exist (any more)."""
  return error_code(exc) in NOT_FOUND_CODES or any(
    m in error_message(exc) for m in NOT_FOUND_MESSAGES
  )


def retry_after(exc: RateLimited) -> timedelta | None:
  """How long KuCoin asks to wait before the throttled quota resets, if it said so.

  typed-kucoin attaches the `gw-ratelimit-*` headers as a mapping with a `reset` key
  (the last argument of the error); older releases attach nothing, giving `None`.
  """
  for arg in reversed(exc.args):
    if isinstance(arg, Mapping):
      reset = cast(Mapping[str, object], arg).get('reset')
      if isinstance(reset, timedelta):
        return reset
