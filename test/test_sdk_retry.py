"""Tests for retry timing, logging, and invocation-context propagation."""

from typing_extensions import AsyncIterator, Callable
import asyncio
import math

import pytest

from tribulnation.sdk.core.invocations import Context, SDK
from tribulnation.sdk.core.invocations.middleware import full_jitter, retry


class RetriableError(Exception):
  """Error used to exercise retry behavior."""


async def invoke_retry(
  monkeypatch: pytest.MonkeyPatch, *,
  base_delay: float = 1,
  max_delay: float | None = None,
  jitter: Callable[[float], float] | None = None,
) -> tuple[list[float], list[float]]:
  """Invoke a failing coroutine and return sleep and logger delays."""
  sleeps: list[float] = []
  logged: list[float] = []

  async def sleep(delay: float):
    """Capture a retry delay without waiting."""
    sleeps.append(delay)

  def logger(
    fn, ctx, *, args, kwargs, exception, retries, delay,
  ):
    """Capture the effective delay passed to the retry logger."""
    logged.append(delay)

  monkeypatch.setattr(asyncio, 'sleep', sleep)

  calls = 0

  async def target():
    """Fail twice before succeeding."""
    nonlocal calls
    calls += 1
    if calls < 3:
      raise RetriableError
    return 'ok'

  middleware = retry(
    RetriableError,
    max_retries=2,
    base_delay=base_delay,
    max_delay=max_delay,
    jitter=jitter,
    log=logger,
  )
  wrapped = middleware(target, Context(path=('report', 'history')))
  assert await wrapped() == 'ok'
  return sleeps, logged


async def test_retry_preserves_existing_delays_without_jitter(
  monkeypatch: pytest.MonkeyPatch,
):
  """Omitting jitter preserves the exact exponential delay sequence."""
  sleeps, logged = await invoke_retry(monkeypatch)
  assert sleeps == [2, 4]
  assert logged == sleeps


async def test_retry_applies_jitter_after_max_delay(
  monkeypatch: pytest.MonkeyPatch,
):
  """Jitter receives the capped delay and controls the effective delay."""
  caps: list[float] = []

  def half_jitter(delay: float) -> float:
    """Return half the supplied cap."""
    caps.append(delay)
    return delay / 2

  sleeps, logged = await invoke_retry(
    monkeypatch, base_delay=4, max_delay=5, jitter=half_jitter,
  )
  assert caps == [5, 5]
  assert sleeps == [2.5, 2.5]
  assert logged == sleeps


@pytest.mark.parametrize('result', [-1, 3, math.inf, math.nan])
async def test_retry_rejects_invalid_jitter(
  monkeypatch: pytest.MonkeyPatch, result: float,
):
  """Jitter must return a finite delay within the supplied cap."""
  async def sleep(delay: float):
    """Fail if invalid jitter reaches the sleep boundary."""
    pytest.fail(f'unexpected sleep with {delay}')

  monkeypatch.setattr(asyncio, 'sleep', sleep)

  async def target():
    """Raise an error eligible for retry."""
    raise RetriableError

  wrapped = retry(
    RetriableError,
    max_retries=1,
    jitter=lambda _: result,
    log=None,
  )(target, Context())

  with pytest.raises(ValueError, match='expected a finite delay between'):
    await wrapped()


def test_full_jitter_accepts_injected_randomness():
  """Full jitter supports deterministic random-number injection."""
  assert full_jitter(8, random=lambda: 0.25) == 2


async def test_context_retries_nested_task_without_restarting_generator():
  """Reporting contexts propagate into tasks and retry only atomic methods."""
  class Report(SDK):
    """Minimal report with an async history generator and atomic request."""
    history_calls: int
    request_calls: int

    def __init__(self):
      self.history_calls = 0
      self.request_calls = 0

    @SDK.method
    async def request(self) -> str:
      """Fail the first atomic request."""
      self.request_calls += 1
      if self.request_calls == 1:
        raise RetriableError
      return 'record'

    @SDK.method
    async def history(self) -> AsyncIterator[str]:
      """Create an atomic request task under the reporting context."""
      self.history_calls += 1
      yield await asyncio.create_task(self.request())

  report = Report()
  context = Context().retried(
    RetriableError,
    max_retries=1,
    base_delay=0,
  )

  with context.use():
    records = [record async for record in report.history()]

  assert records == ['record']
  assert report.history_calls == 1
  assert report.request_calls == 2


async def test_default_retry_logger_excludes_sensitive_values(
  monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
):
  """Default retry logs contain metadata without arguments or exception text."""
  class SecretSelf:
    """Object whose representation contains a credential."""
    def __repr__(self) -> str:
      """Return a deliberately sensitive representation."""
      return 'SecretSelf(api_key=repr-secret)'

  async def sleep(delay: float):
    """Avoid waiting during the retry."""

  monkeypatch.setattr(asyncio, 'sleep', sleep)

  calls = 0

  async def target(self: SecretSelf, secret: str):
    """Fail once with a sensitive exception message."""
    nonlocal calls
    calls += 1
    if calls == 1:
      raise RetriableError('https://alchemy.example/v2/secret-key')
    return 'ok'

  wrapped = retry(
    RetriableError,
    max_retries=1,
  )(target, Context(path=('report', 'history', 'get_tx')))
  assert await wrapped(SecretSelf(), 'argument-secret') == 'ok'

  output = capsys.readouterr().out
  assert output == (
    'Retry 1 for report.history.get_tx after RetriableError; sleeping 2.00s\n'
  )
  assert 'repr-secret' not in output
  assert 'argument-secret' not in output
  assert 'secret-key' not in output
