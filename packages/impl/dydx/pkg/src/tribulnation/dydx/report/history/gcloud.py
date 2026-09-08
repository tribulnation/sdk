"""Typed boundary over `google-cloud-bigquery` and `google-auth`.

Both ship `py.typed`, but the members this package reads are unannotated: a query job's
`job_id` and `cache_hit`, the row iteration of its result set, and
`Credentials.from_service_account_file`. Under the no-implicit-Any rules every such
access is an error, so this module is the one place that touches them. Each read goes
through `getattr` or a declared supertype and is checked at runtime, so a value leaving
here carries the type it claims.
"""

from typing_extensions import Any, Callable, Iterable
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


def result_rows(job: bigquery.QueryJob) -> Iterable[object]:
  """The job's result set, through the `Iterable` protocol the library leaves unannotated."""
  return job.result()


def rows(job: bigquery.QueryJob) -> list[dict[str, Any]]:
  """
  Every row of the job's result set, as `{column: value}` dicts.

  Args:
    job: A started query job; blocks until it completes.

  Raises:
    TypeError: The result set yields something other than a `Row`.
  """
  out: list[dict[str, Any]] = []
  for row in result_rows(job):
    if not isinstance(row, bigquery.Row):
      raise TypeError(f'BigQuery result yielded {type(row).__name__}, not Row')
    out.append(dict(row.items()))
  return out


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
