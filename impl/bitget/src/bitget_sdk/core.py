from typing_extensions import TypeVar
from dataclasses import dataclass
import inspect

from trading_sdk.core import ApiError, AuthError, Error, NetworkError, UserError, ValidationError

from bitget import Bitget
from bitget.core import exc

Fn = TypeVar('Fn')

def wrap_exceptions(fn) -> Fn:
  if inspect.iscoroutinefunction(fn):
    async def wrapper(*args, **kwargs):
      try:
        return await fn(*args, **kwargs)
      except exc.ApiError as e:
        raise ApiError(*e.args) from e
      except exc.AuthError as e:
        raise AuthError(*e.args) from e
      except exc.NetworkError as e:
        raise NetworkError(*e.args) from e
      except exc.UserError as e:
        raise UserError(*e.args) from e
      except exc.ValidationError as e:
        raise ValidationError(*e.args) from e
      except exc.Error as e:
        raise Error(*e.args) from e
    return wrapper
  elif inspect.isgeneratorfunction(fn):
    async def wrapper(*args, **kwargs):
      try:
        return await fn(*args, **kwargs)
      except exc.ApiError as e:
        raise ApiError(*e.args) from e
      except exc.AuthError as e:
        raise AuthError(*e.args) from e
      except exc.NetworkError as e:
        raise NetworkError(*e.args) from e
      except exc.UserError as e:
        raise UserError(*e.args) from e
      except exc.ValidationError as e:
        raise ValidationError(*e.args) from e
      except exc.Error as e:
        raise Error(*e.args) from e
    return wrapper
  else:
    raise ValueError(f"Function {fn.__name__} is not a coroutine or generator function")

@dataclass
class SdkMixin:
  client: Bitget
  validate: bool = True

  @classmethod
  def new(
    cls, access_key: str | None = None, secret_key: str | None = None, passphrase: str | None = None, *,
    validate: bool = True
  ):
    client = Bitget.new(access_key=access_key, secret_key=secret_key, passphrase=passphrase)
    return cls(client=client, validate=validate)

  async def __aenter__(self):
    await self.client.__aenter__()
    return self

  async def __aexit__(self, exc_type, exc_value, traceback):
    await self.client.__aexit__(exc_type, exc_value, traceback)