"""Typed boundary over `google-cloud-bigquery` and `google-auth`.

Both ship `py.typed`, but the members this package reads are unannotated: a query job's
`job_id` and `cache_hit`, the row iteration of its result set, and
`Credentials.from_service_account_file`. Under the no-implicit-Any rules every such
access is an error, so this module is the one place that touches them. Each read goes
through `getattr` or a declared supertype and is checked at runtime, so a value leaving
here carries the type it claims.
"""

from typing_extensions import Any, Callable, Iterable, TypeVar
import asyncio
import requests

from tribulnation.sdk import SDK, NetworkError
from google.cloud import bigquery
from google.oauth2 import service_account


def job_id(job: bigquery.QueryJob) -> str | None:
  """The job's server-assigned id, `None` until the job is started."""
  value: object = getattr(job, 'job_id')
  if value is not None and not isinstance(value, str):
    raise TypeError(f'BigQuery job id is {type(value).__name__}, not str')
  return value


def cache_hit(job: bigquery.QueryJob) -> bool:
  """Whether the job's results were served from the query cache."""
  value: object = getattr(job, 'cache_hit')
  return bool(value)


T = TypeVar('T')


@SDK.method
async def call_google(fetch: Callable[[], T]) -> T:
  """Retry a blocking Google result request after translating transport failures."""
  try:
    return await asyncio.to_thread(fetch)
  except (requests.ConnectionError, requests.Timeout) as error:
    raise NetworkError(*error.args) from error


async def rows(job: bigquery.QueryJob) -> list[dict[str, Any]]:
  """Collect result pages with retries on requests, preserving the submitted job."""
  result = await call_google(job.result)
  request: Callable[..., object] = getattr(result, 'api_request')
  loop = asyncio.get_running_loop()

  def fetch_page(**kwargs: Any) -> object:
    """Bridge the blocking iterator's page request to the async SDK middleware."""
    return asyncio.run_coroutine_threadsafe(
      call_google(lambda: request(**kwargs)), loop
    ).result()

  setattr(result, 'api_request', fetch_page)

  def collect(values: Iterable[object]) -> list[dict[str, Any]]:
    """Consume the blocking iterator outside the event loop."""
    out: list[dict[str, Any]] = []
    for row in values:
      if not isinstance(row, bigquery.Row):
        raise TypeError(f'BigQuery result yielded {type(row).__name__}, not Row')
      out.append(dict(row.items()))
    return out

  return await asyncio.to_thread(collect, result)


def service_account_credentials(path: str) -> service_account.Credentials:
  """
  Credentials read from a service account JSON key file.

  Args:
    path: Path to the key file.
  """
  loader: Callable[[str], object] = getattr(
    service_account.Credentials, 'from_service_account_file'
  )
  credentials = loader(path)
  if not isinstance(credentials, service_account.Credentials):
    raise TypeError(
      f'google-auth returned {type(credentials).__name__}, not service account credentials'
    )
  return credentials
