"""Catalogue coverage: the raw IDs an SDK surface emits, checked against the catalogue's
per-platform translations.

The SDK returns venue-native IDs and `tribulnation.catalogue` maps them to canonical
assets and instruments, so every impl commits to an ID form (a symbol, a token index, a
contract address) that the catalogue's keys for that platform must share. Nothing else
enforces that contract: `impl.toml` declares the form under `[ids]`, `check_keys`
verifies the catalogue's keys have it, and `gap` reports which IDs a live surface
returned that the catalogue cannot translate yet.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing_extensions import Iterable, Literal, Mapping, NamedTuple
import re

from tribulnation.catalogue import Catalogue
from tribulnation.sdk import Context, NetworkError, RateLimited
from tribulnation.sdk.earn import Earn
from tribulnation.sdk.market import TradingVenue
from tribulnation.sdk.reporting import Report
from tribulnation.sdk.wallet import Wallet

AssetIdKind = Literal['symbol', 'index', 'address']
ASSET_ID_PATTERNS: dict[AssetIdKind, re.Pattern[str]] = {
  'symbol': re.compile(r'^(?!\d+$)(?!0x[0-9a-fA-F]{40}$)\S+$'),
  'index': re.compile(r'^\d+$'),
  'address': re.compile(r'^(native|0x[0-9a-fA-F]{40})$'),
}
"""What a catalogue translation key must look like for each declared asset-ID form."""
TESTNET_SUFFIX = '_testnet'


def platform_of(venue: str) -> str:
  """
  The catalogue platform a venue's IDs are keyed under: testnets share the mainnet's.

  Args:
    venue: An account's `venue` id, e.g. `hyperliquid_testnet`.
  """
  return venue.removesuffix(TESTNET_SUFFIX)


def load_catalogue(path: Path | None = None, *, root: Path | None = None) -> Catalogue:
  """
  Load the catalogue from an explicit data folder, else a sibling `catalogue` checkout's
  `data/`, else the cached public download.

  Args:
    path: A catalogue data folder.
    root: The sdk repo root, whose parent may hold a `catalogue` checkout.
  """
  if path is not None:
    return Catalogue.load(path)
  if root is not None and (sibling := root.parent / 'catalogue' / 'data').is_dir():
    return Catalogue.load(sibling)
  return Catalogue.load(silent=True)


class KeyFinding(NamedTuple):
  """A catalogue translation key that doesn't match the venue's declared asset-ID form."""

  venue: str
  key: str
  kind: AssetIdKind


def check_keys(
  kinds: Mapping[str, AssetIdKind], catalogue: Catalogue
) -> list[KeyFinding]:
  """
  Every asset-translation key that breaks its venue's declared ID form.

  Args:
    kinds: Venue slug to the asset-ID form its `impl.toml` declares.
    catalogue: The loaded catalogue.
  """
  findings: list[KeyFinding] = []
  for venue, kind in sorted(kinds.items()):
    pattern = ASSET_ID_PATTERNS[kind]
    for key in catalogue.asset_translations.get(venue, {}):
      if not pattern.match(key):
        findings.append(KeyFinding(venue, key, kind))
  return findings


@dataclass
class Ids:
  """The raw IDs one surface returned, by what the catalogue would translate them as."""

  assets: set[str] = field(default_factory=set[str])
  networks: set[str] = field(default_factory=set[str])
  spot_markets: set[str] = field(default_factory=set[str])
  """Market IDs, prefixed `<exchange>:` when the exchange id is non-empty."""
  perp_markets: set[str] = field(default_factory=set[str])
  positions: set[str] = field(default_factory=set[str])
  """Instrument IDs from a snapshot, which may be spot or perpetual."""

  def merge(self, other: 'Ids'):
    """
    Fold another surface's IDs into this one.

    Args:
      other: The IDs to add.
    """
    self.assets |= other.assets
    self.networks |= other.networks
    self.spot_markets |= other.spot_markets
    self.perp_markets |= other.perp_markets
    self.positions |= other.positions


@dataclass
class Gap:
  """The subset of an `Ids` the catalogue cannot translate for a platform."""

  assets: list[str]
  networks: list[str]
  spot_markets: list[str]
  perp_markets: list[str]
  positions: list[str]

  @property
  def empty(self) -> bool:
    return not any(
      (self.assets, self.networks, self.spot_markets, self.perp_markets, self.positions)
    )


def market_key(exchange_id: str, market_id: str) -> str:
  """
  The catalogue instrument key for a market: `<exchange>:<market>` when the exchange
  id is non-empty, the bare market id otherwise.

  Args:
    exchange_id: The SDK exchange id, `''` for a venue's default exchange.
    market_id: The SDK market id.
  """
  return f'{exchange_id}:{market_id}' if exchange_id else market_id


def instrument_keys(instruments: Mapping[str, object]) -> set[str]:
  """
  Every form an instrument table's keys are matched under: as written, and with any
  `<exchange>:` prefix stripped, since spot tables key the bare market id even when the
  entry names an exchange.

  Args:
    instruments: One platform's spot or perpetual instrument table.
  """
  keys = set(instruments)
  keys |= {k.split(':', 1)[1] for k in instruments if ':' in k}
  return keys


def gap(platform: str, ids: Ids, catalogue: Catalogue) -> Gap:
  """
  Which of a surface's IDs the catalogue has no entry for under `platform`.

  Args:
    platform: The catalogue platform slug.
    ids: The IDs a surface returned.
    catalogue: The loaded catalogue.
  """
  assets = set(catalogue.asset_translations.get(platform, {}))
  networks = set(catalogue.network_translations.get(platform, {}))
  spot = instrument_keys(catalogue.spot_instruments.get(platform, {}))
  perp = instrument_keys(catalogue.perpetual_instruments.get(platform, {}))

  def missing(found: Iterable[str], known: set[str]) -> list[str]:
    return sorted(
      x for x in found if x not in known and x.split(':', 1)[-1] not in known
    )

  return Gap(
    assets=missing(ids.assets, assets),
    networks=missing(ids.networks, networks),
    spot_markets=missing(ids.spot_markets, spot),
    perp_markets=missing(ids.perp_markets, perp),
    positions=missing(ids.positions, spot | perp),
  )


def retried():
  """The retry policy every live collector runs under."""
  return Context().retried(NetworkError, RateLimited, max_retries=3).use()


async def earn_ids(earn: Earn) -> Ids:
  """
  The asset IDs an earn surface's instruments carry.

  Args:
    earn: The venue's earn implementation.
  """
  with retried():
    instruments = await earn.instruments()
  ids = Ids()
  for i in instruments:
    ids.assets.add(i.asset)
    if i.yield_asset is not None:
      ids.assets.add(i.yield_asset)
  return ids


async def wallet_ids(wallet: Wallet) -> Ids:
  """
  The asset and network IDs a wallet surface's deposit and withdrawal methods carry.

  Args:
    wallet: The venue's wallet implementation.
  """
  with retried():
    deposits = await wallet.deposit_methods()
    withdrawals = await wallet.withdrawal_methods()
  ids = Ids()
  for m in (*deposits, *withdrawals):
    ids.assets.add(m.asset)
    ids.networks.add(m.network)
  return ids


async def report_ids(report: Report) -> Ids:
  """
  The asset and instrument IDs a report surface's snapshot carries.

  Args:
    report: The venue's report implementation.
  """
  with retried():
    record = await report.snapshot()
  return Ids(
    assets=set(record.snapshot.balances), positions=set(record.snapshot.positions)
  )


async def market_ids(venue: TradingVenue) -> Ids:
  """
  The market IDs every exchange of a trading venue lists, keyed the way the catalogue
  keys instruments.

  Args:
    venue: The venue's market implementation.
  """
  ids = Ids()
  with retried():
    for description in await venue.exchanges():
      exchange = await venue.exchange(description['id'])
      keys = {market_key(description['id'], m) for m in await exchange.markets()}
      if description['type'] == 'spot':
        ids.spot_markets |= keys
      else:
        ids.perp_markets |= keys
  return ids
