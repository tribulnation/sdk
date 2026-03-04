from typing_extensions import Any, Mapping
from dataclasses import dataclass, field
from functools import wraps
import httpx

from ethereum_sdk.core import UserError, NetworkError

class HttpClient:
  async def __aenter__(self):
    self._client = httpx.AsyncClient()
    await self._client.__aenter__()
    return self
  
  async def __aexit__(self, exc_type, exc_value, traceback):
    if (client := getattr(self, '_client', None)) is not None:
      await client.__aexit__(exc_type, exc_value, traceback)
      self._client = None

  @property
  def client(self) -> httpx.AsyncClient:
    if (client := getattr(self, '_client', None)) is None:
      raise UserError('Client must be used as context manager: `async with ...: ...`')
    return client
  
  @staticmethod
  def with_client(fn):
    @wraps(fn)
    async def wrapper(self, *args, **kwargs):
      if getattr(self, '_client', None) is None:
        async with self:
          return await fn(self, *args, **kwargs)
      else:
        return await fn(self, *args, **kwargs)
      
    return wrapper

  @with_client
  async def request(
    self, method: str, url: str,
    *,
    content: httpx._types.RequestContent | None = None,
    data: httpx._types.RequestData | None = None,
    files: httpx._types.RequestFiles | None = None,
    json: Any | None = None,
    params: httpx._types.QueryParamTypes | None = None,
    headers: Mapping[str, str] | None = None,
    cookies: httpx._types.CookieTypes | None = None,
    auth: httpx._types.AuthTypes | httpx._client.UseClientDefault | None = httpx.USE_CLIENT_DEFAULT,
    follow_redirects: bool | httpx._client.UseClientDefault = httpx.USE_CLIENT_DEFAULT,
    timeout: httpx._types.TimeoutTypes | httpx._client.UseClientDefault = httpx.USE_CLIENT_DEFAULT,
    extensions: httpx._types.RequestExtensions | None = None,
  ):
    try:
      return await self.client.request(
        method, url, params=params, cookies=cookies, json=json,
        content=content, data=data, files=files, auth=auth, follow_redirects=follow_redirects,
        timeout=timeout, extensions=extensions,
        headers={
          'User-Agent': 'trading-sdk',
          **(headers or {})
        }
      )
    except httpx.HTTPError as e:
      raise NetworkError(*e.args) from e

@dataclass
class HttpMixin:
  base_url: str = field(kw_only=True)
  http: HttpClient = field(kw_only=True, default_factory=HttpClient)

  async def __aenter__(self):
    await self.http.__aenter__()
    return self
  
  async def __aexit__(self, exc_type, exc_value, traceback):
    await self.http.__aexit__(exc_type, exc_value, traceback)

  async def request(
    self, method: str, path: str,
    *,
    content: httpx._types.RequestContent | None = None,
    data: httpx._types.RequestData | None = None,
    files: httpx._types.RequestFiles | None = None,
    json: Any | None = None,
    params: httpx._types.QueryParamTypes | None = None,
    headers: Mapping[str, str] | None = None,
    cookies: httpx._types.CookieTypes | None = None,
    auth: httpx._types.AuthTypes | httpx._client.UseClientDefault | None = httpx.USE_CLIENT_DEFAULT,
    follow_redirects: bool | httpx._client.UseClientDefault = httpx.USE_CLIENT_DEFAULT,
    timeout: httpx._types.TimeoutTypes | httpx._client.UseClientDefault = httpx.USE_CLIENT_DEFAULT,
    extensions: httpx._types.RequestExtensions | None = None,
  ):
    return await self.http.request(
      method, self.base_url + path, params=params, headers=headers, cookies=cookies, json=json,
      content=content, data=data, files=files, auth=auth, follow_redirects=follow_redirects,
      timeout=timeout, extensions=extensions,
    )