"""Keep loop-bound transports and rate limiters on one integration-session loop."""

import asyncio

import pytest

LOOP: pytest.StashKey[asyncio.AbstractEventLoop] = pytest.StashKey()


def loop_of(config: pytest.Config) -> asyncio.AbstractEventLoop:
  """Create one loop for the session; individual SDK contexts still own clients."""
  loop = config.stash.get(LOOP, None)
  if loop is None:
    loop = asyncio.new_event_loop()
    config.stash[LOOP] = loop
  return loop
