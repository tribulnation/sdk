"""CLI entry points for catalogue coverage: `catalogue check` verifies the catalogue's
translation keys follow each venue's declared ID form, `catalogue coverage` runs the live
surfaces and lists the IDs the catalogue cannot translate yet.
"""

from pathlib import Path
from typing_extensions import Annotated, Any, Awaitable, Callable
import asyncio
import json

import typer

from sdk_dev.catalogue import (
  AssetIdKind,
  Gap,
  Ids,
  check_keys,
  earn_ids,
  gap,
  load_catalogue,
  market_ids,
  platform_of,
  report_ids,
  wallet_ids,
)
from sdk_dev.repo import IMPL_DIR, NotACheckout, repo_root
from sdk_dev.support import load_impl_files
from tribulnation.sdk import SDK

app = typer.Typer(help='Check the catalogue against what the SDK surfaces emit.')

PATH_HELP = (
  'Catalogue data folder. Defaults to a sibling `catalogue` checkout, else the cached '
  'public download.'
)
SURFACES = ('earn', 'wallet', 'report', 'market')
SHOWN = 30
"""How many untranslated IDs to print per line before eliding."""


def root_or_exit(command: str) -> Path:
  """
  The sdk repo root, or exit with a hint.

  Args:
    command: The command name, for the hint.
  """
  try:
    return repo_root()
  except NotACheckout as e:
    typer.echo(
      f'{e}\nRun `sdk-dev catalogue {command}` from inside the sdk repo checkout.',
      err=True,
    )
    raise typer.Exit(code=1)


@app.command('check')
def check(
  path: Annotated[Path | None, typer.Option('--path', help=PATH_HELP)] = None,
):
  """
  Verify that every catalogue asset-translation key follows the ID form the venue's
  `impl.toml` declares under `[ids]`, and list venues that declare none.
  """
  root = root_or_exit('check')
  impls = load_impl_files(root / IMPL_DIR)
  kinds: dict[str, AssetIdKind] = {}
  undeclared: list[str] = []
  for slug, data in sorted(impls.items()):
    if data.ids is None:
      undeclared.append(slug)
    else:
      kinds[slug] = data.ids.asset
  catalogue = load_catalogue(path, root=root)
  findings = check_keys(kinds, catalogue)
  for slug, kind in sorted(kinds.items()):
    translations = len(catalogue.asset_translations.get(slug, {}))
    spot = len(catalogue.spot_instruments.get(slug, {}))
    perp = len(catalogue.perpetual_instruments.get(slug, {}))
    typer.echo(
      f'{slug:<12} asset ids: {kind:<8} translations: {translations:>4}  '
      f'spot: {spot:>4}  perp: {perp:>4}'
    )
  for f in findings:
    typer.echo(f'  {f.venue}: key {f.key!r} is not a {f.kind}')
  if undeclared:
    typer.echo(f'\nNo `[ids]` in impl.toml: {", ".join(undeclared)}.')
  if findings:
    typer.echo(f'\n{len(findings)} key{"" if len(findings) == 1 else "s"} off form.')
    raise typer.Exit(code=1)
  typer.echo('Translation keys match every declared ID form.')


Collector = Callable[[Any], Awaitable[Ids]]


def loaders(accounts: str) -> dict[str, tuple[dict[str, Any], Collector]]:
  """
  Per surface, the `{account id: implementation}` map and the collector to run on it.

  Args:
    accounts: Path to the accounts TOML.
  """
  from tribulnation.sdk import EarnSDK, MarketSDK, ReportSDK, WalletSDK

  def safe(sdk: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for id in sdk.all_accounts if hasattr(sdk, 'all_accounts') else sdk.accounts:
      try:
        impl = sdk.venue(id)
        out[id] = impl if not asyncio.iscoroutine(impl) else asyncio.run(impl)
      except (NotImplementedError, ImportError, ValueError):
        continue
    return out

  return {
    'earn': (safe(EarnSDK.load(accounts)), earn_ids),
    'wallet': (safe(WalletSDK.load(accounts)), wallet_ids),
    'report': (safe(ReportSDK.load(accounts)), report_ids),
    'market': (safe(MarketSDK.load(accounts)), market_ids),
  }


async def collect(impl: SDK, collector: Collector) -> Ids:
  """
  Run one collector inside the implementation's resource scope.

  Args:
    impl: The surface implementation.
    collector: The collector for its surface.
  """
  async with impl:
    return await collector(impl)


def describe(gap: Gap) -> list[str]:
  """
  One line per non-empty category of a gap, eliding long lists.

  Args:
    gap: The untranslated IDs.
  """
  lines: list[str] = []
  for name, ids in (
    ('assets', gap.assets),
    ('networks', gap.networks),
    ('spot markets', gap.spot_markets),
    ('perp markets', gap.perp_markets),
    ('positions', gap.positions),
  ):
    if ids:
      shown = ', '.join(ids[:SHOWN]) + (
        f', +{len(ids) - SHOWN} more' if len(ids) > SHOWN else ''
      )
      lines.append(f'    {name} ({len(ids)}): {shown}')
  return lines


@app.command('coverage')
def coverage(
  surfaces: Annotated[
    list[str] | None,
    typer.Argument(help=f'Surfaces to run: {", ".join(SURFACES)}. All when omitted.'),
  ] = None,
  accounts: Annotated[
    str, typer.Option('--accounts', help='Accounts TOML, as for `sdk-dev test`.')
  ] = 'sdk.test.toml',
  path: Annotated[Path | None, typer.Option('--path', help=PATH_HELP)] = None,
  out: Annotated[
    Path | None,
    typer.Option('--json', help='Write every untranslated ID here as JSON.'),
  ] = None,
  only: Annotated[
    list[str] | None,
    typer.Option('--only', help='Account ids to run; repeatable. All when omitted.'),
  ] = None,
):
  """
  Run each configured account's live surfaces and list the asset, network and market IDs
  the catalogue cannot translate for that platform: the catalogue's to-do list per venue.
  """
  from dotenv import load_dotenv

  root = root_or_exit('coverage')
  chosen = surfaces or list(SURFACES)
  unknown = [s for s in chosen if s not in SURFACES]
  if unknown:
    typer.echo(f'Unknown surface(s): {", ".join(unknown)}.', err=True)
    raise typer.Exit(code=1)
  load_dotenv(Path(accounts).expanduser().resolve().parent / '.env')
  catalogue = load_catalogue(path, root=root)
  found = loaders(accounts)
  report: dict[str, dict[str, Any]] = {}
  failures = 0
  for surface in chosen:
    impls, collector = found[surface]
    typer.echo(f'{surface}:')
    for id, impl in impls.items():
      if only and id not in only:
        continue
      platform = platform_of(getattr(impl, 'venue_id', None) or venue_of(accounts, id))
      try:
        ids = asyncio.run(collect(impl, collector))
      except NotImplementedError as e:
        typer.echo(f'  {id:<16} not supported: {str(e)[:100]}')
        continue
      except Exception as e:
        failures += 1
        typer.echo(f'  {id:<16} error: {type(e).__name__}: {str(e)[:120]}')
        continue
      missing = gap(platform, ids, catalogue)
      counts = (
        f'{len(ids.assets)} assets, {len(ids.networks)} networks, '
        f'{len(ids.spot_markets)} spot, {len(ids.perp_markets)} perp, '
        f'{len(ids.positions)} positions'
      )
      status = 'all translated' if missing.empty else 'untranslated:'
      typer.echo(f'  {id:<16} [{platform}] {counts}; {status}')
      for line in describe(missing):
        typer.echo(line)
      report.setdefault(surface, {})[id] = {
        'platform': platform,
        'assets': missing.assets,
        'networks': missing.networks,
        'spot_markets': missing.spot_markets,
        'perp_markets': missing.perp_markets,
        'positions': missing.positions,
      }
  if out is not None:
    out.write_text(json.dumps(report, indent=2) + '\n')
    typer.echo(f'\nWritten to {out}.')
  if failures:
    typer.echo(f'\n{failures} account{"" if failures == 1 else "s"} could not be read.')
    raise typer.Exit(code=1)


def venue_of(accounts: str, id: str) -> str:
  """
  The venue id an account is configured with.

  Args:
    accounts: Path to the accounts TOML.
    id: The account id.
  """
  from tribulnation.sdk.impl.accounts import load_accounts

  return load_accounts(accounts)[id].venue
