"""Asset/network enumeration, shared by `deposit_methods` and `withdrawal_methods`.

Two endpoints, joined. `v2/currency/assets` is the catalogue: every asset Bit2Me
supports, with the `enabled` flag that gates it. Its `network` field is a scalar
display string (`'ETHEREUM (ERC20)'`), so it collapses every multi-chain asset into
one row and cannot be the network source. `v1/wallet/currency/{symbol}/network` is:
it answers with the real per-asset chain list, whose `id` is the machine slug
(`binanceSmartChain`, `tron`) the rest of the wallet API speaks. It is signed and
one call per asset, so results are cached and the sweep is bounded by a semaphore.
"""

from typing_extensions import Collection, Sequence
from dataclasses import dataclass, field
import asyncio

from tribulnation.sdk.core import SDK, ApiError
from tribulnation.bit2me.core import Mixin

from typed_bit2me.v1.wallet.currency.network import CurrencyNetwork

DEFAULT_CONCURRENCY = 8
"""Concurrent per-asset network lookups. An unfiltered sweep is one signed call per
asset (503 today), so it is worth parallelising, but not worth rate-limiting over."""


@dataclass
class AssetNetwork:
  """One asset paired with one network it can move over."""

  asset: str
  network: CurrencyNetwork


@dataclass
class NetworkCache:
  """Per-asset network lists, plus the gate bounding concurrent lookups."""

  networks: dict[str, Sequence[CurrencyNetwork]] = field(
    default_factory=dict[str, Sequence[CurrencyNetwork]]
  )
  gate: asyncio.Semaphore = field(
    default_factory=lambda: asyncio.Semaphore(DEFAULT_CONCURRENCY)
  )


@dataclass(frozen=True, kw_only=True)
class Networks(Mixin):
  """The asset/network join both wallet methods enumerate over."""

  cache: NetworkCache = field(default_factory=NetworkCache)

  @SDK.method
  async def coin_networks(self, coin: str) -> Sequence[CurrencyNetwork]:
    """Every network Bit2Me supports for one asset.

    Args:
      coin: Asset symbol, uppercase.

    Returns:
      The asset's networks, or an empty sequence when it has none: fiat answers
      `404` rather than `[]`, and a few listed crypto assets do return `[]`.
    """
    if (cached := self.cache.networks.get(coin)) is not None:
      return cached
    async with self.cache.gate:
      try:
        networks = await self.call_bit2me(
          lambda: self.client.v1.wallet.currency.network(coin)
        )
      except ApiError as e:
        if e.args[0] != 404:
          raise
        networks = []
    self.cache.networks[coin] = networks
    return networks

  @SDK.method
  async def asset_networks(
    self,
    *,
    assets: Collection[str] | None = None,
    networks: Collection[str] | None = None,
  ) -> Sequence[AssetNetwork]:
    """Enumerate every enabled asset paired with each of its networks.

    Args:
      assets: Keep these assets only. `None` sweeps the whole catalogue, which
        costs one signed call per asset.
      networks: Keep these network ids only.
    """
    catalogue = await self.call_bit2me(self.client.v2.currency.assets.list)
    wanted = [
      symbol
      for symbol, entry in catalogue.items()
      if entry.get('enabled') and (assets is None or symbol in assets)
    ]
    found = await asyncio.gather(*[self.coin_networks(symbol) for symbol in wanted])
    return [
      AssetNetwork(asset=symbol, network=network)
      for symbol, entry in zip(wanted, found)
      for network in entry
      if networks is None or network['id'] in networks
    ]
