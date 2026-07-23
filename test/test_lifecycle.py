"""Tests for declarative async resource lifecycles."""

from dataclasses import dataclass

import pytest

from tribulnation.sdk.core import AsyncResources


@dataclass
class Resource:
  name: str
  events: list[str]
  fail: bool = False

  async def __aenter__(self):
    self.events.append(f'enter:{self.name}')
    if self.fail:
      raise RuntimeError(self.name)
    return self

  async def __aexit__(self, exc_type, exc_value, traceback):
    self.events.append(f'exit:{self.name}')


@dataclass(frozen=True)
class Owner(AsyncResources):
  resources_to_enter: tuple[Resource, ...]
  def resources(self):
    yield from self.resources_to_enter


async def test_async_resources_enter_and_exit_in_order():
  events: list[str] = []
  owner = Owner((Resource('one', events), Resource('two', events)))

  async with owner:
    assert events == ['enter:one', 'enter:two']

  assert events == [
    'enter:one', 'enter:two', 'exit:two', 'exit:one',
  ]


async def test_async_resources_roll_back_partial_entry():
  events: list[str] = []
  owner = Owner((
    Resource('one', events),
    Resource('two', events, fail=True),
  ))

  with pytest.raises(RuntimeError, match='two'):
    await owner.__aenter__()

  assert events == ['enter:one', 'enter:two', 'exit:one']


async def test_async_resources_reject_reentry_and_exit_before_entry():
  events: list[str] = []
  owner = Owner((Resource('one', events),))

  with pytest.raises(RuntimeError, match='not active'):
    await owner.__aexit__(None, None, None)

  await owner.__aenter__()
  with pytest.raises(RuntimeError, match='already active'):
    await owner.__aenter__()
  await owner.__aexit__(None, None, None)
