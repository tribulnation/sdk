from typing_extensions import Literal
from dataclasses import dataclass

class BaseError(Exception):
  detail: str

@dataclass
class NetworkFailure(BaseError):
  code: Literal['NETWORK_FAILURE']

@dataclass
class InvalidParams(BaseError):
  code: Literal['INVALID_PARAMS']

@dataclass
class InvalidResponse(BaseError):
  code: Literal['INVALID_RESPONSE']

@dataclass
class InvalidAuth(BaseError):
  code: Literal['INVALID_AUTH']

UnauthedError = NetworkFailure | InvalidParams | InvalidResponse
AuthedError = UnauthedError | InvalidAuth