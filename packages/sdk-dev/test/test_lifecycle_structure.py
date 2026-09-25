"""Enforce venue resource policies across every implementation package."""

import ast
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from typing_extensions import Any, cast
from unittest.mock import AsyncMock

import pytest
from typed_core import NetworkError as ClientNetworkError
from web3.exceptions import ProviderConnectionError

from tribulnation.sdk import SDK
from tribulnation.sdk.core import Context, ManagedResource, NetworkError

# Each declaration is exercised through its real owner's inherited SDK lifecycle.
OWNERS = [
  ('tribulnation.aster.core', 'Shared', 'client'),
  ('tribulnation.binance.core', 'SdkMixin', 'client'),
  ('tribulnation.binance.market.impl.mixin', 'SharedMixin', 'client'),
  ('tribulnation.bit2me.core.mixin', 'Mixin', 'client'),
  ('tribulnation.bit2me.market.impl.mixin', 'Shared', 'client'),
  ('tribulnation.bitget.core', 'SdkMixin', 'client'),
  ('tribulnation.bybit.core.mixin', 'Mixin', 'client'),
  ('tribulnation.coinbase.core.mixin', 'Shared', 'client'),
  ('tribulnation.deribit.core', 'Mixin', 'client'),
  ('tribulnation.dydx.market.impl.mixin', 'Shared', 'client'),
  ('tribulnation.dydx.report.history.chain', 'ChainHistory', 'comet'),
  ('tribulnation.dydx.report.history.indexer', 'IndexerHistory', 'indexer'),
  ('tribulnation.dydx.report.snapshots', 'Snapshots', 'client'),
  ('tribulnation.ethereum.core.rpc.mixin', 'Mixin', 'node'),
  (
    'tribulnation.ethereum.reporting.history.etherscan',
    'EtherscanHistory',
    'etherscan',
  ),
  ('tribulnation.ethereum.reporting.history.mixin', 'HistoryMixin', 'node'),
  ('tribulnation.ethereum.reporting.history.moralis', 'MoralisHistory', 'moralis'),
  ('tribulnation.ethereum.reporting.snapshots.alchemy', 'AlchemySnapshots', 'alchemy'),
  ('tribulnation.ethereum.reporting.snapshots.moralis', 'MoralisSnapshots', 'moralis'),
  ('tribulnation.ethereum.reporting.snapshots.node', 'NodeSnapshots', 'node'),
  ('tribulnation.hyperliquid.market.impl.mixin', 'Shared', 'client'),
  ('tribulnation.hyperliquid.report.history.main', 'History', 'info'),
  ('tribulnation.kraken.core.mixin', 'Mixin', 'client'),
  ('tribulnation.kraken.market.impl.mixin', 'Shared', 'client'),
  ('tribulnation.kucoin.core', 'Mixin', 'client'),
  ('tribulnation.mexc.core.mixin', 'Mixin', 'client'),
  ('tribulnation.mexc.market.impl.mixin', 'Shared', 'client'),
]


def uncalled(*args: Any, **kwargs: Any):
  """Complete abstract data surfaces that lifecycle tests never invoke."""
  raise AssertionError('Unexpected data method call')


def owner_for(module: str, name: str, attribute: str, client: AsyncMock) -> SDK:
  """Inject a fake transport without constructing network clients or credentials."""
  base = getattr(import_module(module), name)
  concrete = type(
    'LifecycleOwner', (base,), {method: uncalled for method in base.__abstractmethods__}
  )
  owner = object.__new__(concrete)
  if module == 'tribulnation.binance.market.impl.mixin':
    object.__setattr__(owner, 'shared', SimpleNamespace(client=client))
  else:
    object.__setattr__(owner, attribute, client)
  # Additional resources declared by Ethereum history and lazy stream owners.
  if attribute != 'node':
    object.__setattr__(owner, 'node', AsyncMock())
  object.__setattr__(owner, 'streams', {})
  object.__setattr__(owner, 'ws_stack', None)
  return owner


@pytest.mark.parametrize('module,name,attribute', OWNERS)
@pytest.mark.parametrize('phase', ['enter', 'exit'])
async def test_every_owned_client_translates_lifecycle_errors(
  module: str, name: str, attribute: str, phase: str
):
  """Every venue declaration translates connection/cleanup failures without retries."""
  original = (
    ProviderConnectionError('offline')
    if attribute == 'node'
    else ClientNetworkError('offline')
  )
  client = AsyncMock()
  getattr(client, f'__a{phase}__').side_effect = original
  client.__aexit__.return_value = False
  owner = owner_for(module, name, attribute, client)
  adapter = getattr(owner, f'{attribute}_resource')
  assert isinstance(adapter, ManagedResource)
  assert getattr(owner, f'{attribute}_resource') is adapter
  assert cast(ManagedResource[object], adapter).resource is client
  assert any(resource is adapter for resource in owner.resources())
  assert type(owner).__aenter__ is SDK.__aenter__
  assert type(owner).__aexit__ is SDK.__aexit__
  with Context().retried(max_retries=2, base_delay=0).use():
    with pytest.raises(NetworkError) as caught:
      async with owner:
        pass
  assert caught.value.__cause__ is original
  assert client.__aenter__.await_count == 1
  assert client.__aexit__.await_count == (phase == 'exit')


def test_venue_lifecycle_structure():
  """Require data-only ownership declarations and tested policies for raw clients."""
  root = Path(__file__).resolve().parents[2] / 'impl'
  tested = {
    (module, name, f'{attribute}_resource') for module, name, attribute in OWNERS
  }
  found = set[tuple[str, str, str]]()
  nested = {'shared', 'account', 'history_impl', 'snapshots_impl', 'impl', 'chain'}
  for path in root.glob('*/pkg/src/**/*.py'):
    module = '.'.join(path.with_suffix('').parts[path.parts.index('src') + 1 :])
    tree = ast.parse(path.read_text())
    for cls in [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]:
      for fn in cls.body:
        if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
          continue
        assert fn.name not in {'__aenter__', '__aexit__'}, (path, cls.name)
        if fn.name != 'resources':
          continue
        assert isinstance(fn, ast.FunctionDef) and not fn.decorator_list, path
        for node in ast.walk(fn):
          if not isinstance(node, ast.Yield):
            continue
          value = node.value
          if isinstance(value, ast.Attribute):
            key = (module, cls.name, value.attr)
            if key in tested:
              found.add(key)
            else:
              assert value.attr in nested or (
                module == 'tribulnation.dydx.report.history.main'
                and value.attr == 'indexer'
              ), (path, cls.name, ast.unparse(value))
          else:
            # Fresh one-shot closers must carry policies too.
            assert (
              isinstance(value, ast.Call)
              and isinstance(value.func, ast.Name)
              and value.func.id == 'ManagedResource'
            ), (path, ast.unparse(node))
  assert found == tested
  assert getattr(SDK.__aenter__, '__sdk_method__', None) is None
  assert getattr(SDK.__aexit__, '__sdk_method__', None) is None
