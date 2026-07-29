"""Guards the SDK against re-growing hand-written async lifecycles.

`SDK` implements `__aenter__`/`__aexit__` once, in terms of `resources()`. A class that
overrides `__aenter__` instead of `resources()` silently discards every resource declared
by the rest of its MRO -- the failure is invisible (correct results, leaked sockets), so it
has to be caught structurally rather than behaviourally.

`resources()` is a *data* method: overrides compose via `yield from super().resources()`.
Prefer it. If you genuinely need `__aenter__`, add the class here with a reason.
"""

import importlib
import pkgutil

import pytest

from tribulnation.sdk import SDK

# Classes permitted to define their own `__aenter__`/`__aexit__`, with why.
# This list should only ever shrink.
ALLOWED = {
  # Deliberate no-op: MEXC websocket connections open lazily per subscription, so there is
  # nothing to acquire up front and the documented no-op is the correct behaviour.
  'tribulnation.mexc.market.impl.mixin.Shared',
}

IMPL_PACKAGES = [
  'tribulnation.bit2me', 'tribulnation.binance', 'tribulnation.bitget',
  'tribulnation.dydx', 'tribulnation.ethereum', 'tribulnation.hyperliquid',
  'tribulnation.mexc',
]


def _import_everything() -> None:
  """Import every submodule of every installed impl, so subclasses are registered."""
  for name in IMPL_PACKAGES:
    try:
      package = importlib.import_module(name)
    except ImportError:
      continue  # impl not installed in this environment
    for info in pkgutil.walk_packages(package.__path__, prefix=f'{name}.'):
      try:
        importlib.import_module(info.name)
      except Exception:
        # Optional extras and provider-specific modules may not import here; the classes
        # that do matter are reachable through the packages that did.
        continue


def _sdk_subclasses() -> set[type]:
  found = set[type]()
  def walk(cls: type) -> None:
    for sub in cls.__subclasses__():
      if sub not in found:
        found.add(sub)
        walk(sub)
  walk(SDK)
  return found


def test_sdk_subclasses_declare_resources_not_aenter():
  _import_everything()
  offenders = sorted(
    f'{cls.__module__}.{cls.__qualname__}'
    for cls in _sdk_subclasses()
    if '__aenter__' in vars(cls) or '__aexit__' in vars(cls)
  )
  unexpected = [name for name in offenders if name not in ALLOWED]
  assert not unexpected, (
    'These SDK subclasses define __aenter__/__aexit__ instead of resources(), which '
    'silently discards resources declared elsewhere in their MRO:\n  '
    + '\n  '.join(unexpected)
  )


def test_resources_is_not_an_sdk_method():
  """`resources` must stay undecorated.

  It is a sync generator function, so `@SDK.method` would open and close the `Context`
  span around generator *creation* rather than iteration -- an empty span, with the body
  invisible to middleware.
  """
  assert not hasattr(SDK.resources, '__sdk_method__')


@pytest.mark.parametrize('name', sorted(ALLOWED))
def test_allowlist_entries_still_exist(name: str):
  """A stale allowlist entry hides a real regression, so fail when one goes missing."""
  _import_everything()
  module, _, qualname = name.rpartition('.')
  try:
    cls = getattr(importlib.import_module(module), qualname)
  except (ImportError, AttributeError):
    pytest.skip(f'{name} not importable in this environment')
  assert '__aenter__' in vars(cls) or '__aexit__' in vars(cls), (
    f'{name} no longer defines a lifecycle -- remove it from ALLOWED.'
  )
