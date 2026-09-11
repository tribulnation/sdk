"""Local consistency reports and credential-free release evidence verification."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import tomllib

from dotenv import load_dotenv
import pydantic
import typer
from typing_extensions import Annotated, Literal

from tribulnation.catalogue import Catalogue
from tribulnation.sdk import MarketSDK
from tribulnation.sdk.impl.accounts import Account
from sdk_dev.repo import repo_root
from sdk_dev.support import load_impl_files

app = typer.Typer(help='Verify recorded local checks without exchange credentials.')


def load_snapshot(path: Path) -> Catalogue:
  """Require explicit on-disk data; verification never downloads a mutable cache."""
  if not path.is_dir() or not (path / 'assets').is_dir():
    raise ValueError('Catalogue must be an existing data directory with assets')
  return Catalogue.load(path)


def configured_sdk(accounts: Path | None) -> MarketSDK:
  """Parse accounts without validating credentials for unrelated venues."""
  if accounts is None:
    return MarketSDK()
  load_dotenv(accounts.resolve().parent / '.env')
  with accounts.open('rb') as stream:
    data = tomllib.load(stream)
  parsed = pydantic.TypeAdapter(dict[str, Account]).validate_python(
    data.get('accounts', {})
  )
  return MarketSDK(accounts=parsed)


def select_account(sdk: MarketSDK, venue: str, account: str | None) -> str:
  """Choose one exact mainnet account, rejecting ambiguous aliases or testnets."""
  matches = [key for key, value in sdk.all_accounts.items() if value.venue == venue]
  if account is not None:
    if account not in matches:
      raise ValueError('Selected account does not match the requested mainnet venue')
    return account
  configured = [key for key in matches if key in sdk.accounts]
  if len(configured) == 1:
    return configured[0]
  if not configured and venue in matches:
    return venue
  raise ValueError(
    'Configure a matching account or select one explicitly with --account'
  )


def test_consistency(
  venue: Annotated[str, typer.Argument(help='Exact mainnet venue slug.')],
  catalogue: Annotated[Path, typer.Option(help='Explicit Catalogue data directory.')],
  output: Annotated[
    Path, typer.Option(help='New report directory; never overwrite an old run.')
  ],
  accounts: Annotated[
    Path | None, typer.Option(help='Optional accounts TOML; public defaults otherwise.')
  ] = None,
  account: Annotated[
    str | None,
    typer.Option(help='Exact account alias when configuration is ambiguous.'),
  ] = None,
):
  """Run read-only SDK/Catalogue consistency checks and capture fingerprints automatically."""
  from sdk_dev.consistency import collect, verify_payload
  from sdk_dev.evidence import capture, write_report

  root = repo_root()
  try:
    if output.exists():
      raise ValueError('Report directory already exists; choose a new path')
    data = load_snapshot(catalogue)
    sdk = configured_sdk(accounts)
    selected = select_account(sdk, venue, account)
    started = datetime.now(timezone.utc)
    before = capture(root, venue, catalogue)
    typer.echo(
      f'Checking {venue}: discovery, snapshots, quote consistency and Catalogue IDs…'
    )

    async def run() -> dict[str, object]:
      """Close all lazily created venue clients when collection finishes or fails."""
      async with sdk:
        return await collect(sdk, selected, venue, data)

    payload = asyncio.run(run())
    after = capture(root, venue, catalogue)
    write_report(
      output,
      before=before,
      after=after,
      payload=payload,
      started=started,
      finished=datetime.now(timezone.utc),
    )
    typer.echo(f'Recorded {output}; checking release eligibility…')
    verify_payload(payload, catalogue=data, root=root)
  except Exception as exception:
    # Account configuration validation errors can contain credentials. The saved
    # check payload contains sanitized public findings; never print raw exceptions.
    typer.echo(
      f'Not release-verified ({type(exception).__name__}). See the report if recorded.',
      err=True,
    )
    raise typer.Exit(1) from None
  typer.echo(
    'Consistency coverage policy satisfied; use sdk-dev results verify before release.'
  )


def verify_one(
  root: Path,
  report: Path,
  catalogue: Path,
  *,
  venue: str | None = None,
  scope: Literal['surfaces', 'consistency'] | None = None,
):
  """Verify both content provenance and the independently reconstructed check inventory."""
  from sdk_dev.consistency import verify_payload
  from sdk_dev.evidence import verify_report

  payload = verify_report(root, report, catalogue)
  if venue is not None and payload.get('venue') != venue:
    raise ValueError('Report venue does not match the release package')
  actual = 'surfaces' if payload.get('scope') == 'surfaces' else 'consistency'
  if scope is not None and actual != scope:
    raise ValueError(f'{venue}: expected {scope} evidence')
  if payload.get('scope') == 'surfaces':
    from sdk_dev.read_evidence import verify_payload as verify_surfaces

    verify_surfaces(payload, root=root)
  else:
    verify_payload(payload, catalogue=load_snapshot(catalogue), root=root)


def test_surfaces(
  venue: Annotated[str, typer.Argument(help='Exact mainnet implementation slug.')],
  catalogue: Annotated[Path, typer.Option(help='Explicit Catalogue data directory.')],
  output: Annotated[Path, typer.Option(help='New evidence directory.')],
  accounts: Annotated[
    Path, typer.Option(help='Accounts TOML for supported read suites.')
  ],
  account: Annotated[
    str | None, typer.Option(help='Exact configured account alias.')
  ] = None,
  testnet_account: Annotated[
    str | None,
    typer.Option(
      help='Deribit only: private Report account on testnet; metadata stays mainnet.'
    ),
  ] = None,
):
  """Record all supported read-only suites without saving private records."""
  from sdk_dev.evidence import capture, write_report
  from sdk_dev.read_evidence import collect, collect_deribit, verify_payload

  try:
    if output.exists():
      raise ValueError('Report directory already exists')
    load_snapshot(catalogue)
    sdk = configured_sdk(accounts)
    selected = select_account(sdk, venue, account)
    if testnet_account is not None:
      if venue != 'deribit':
        raise ValueError('Split qualification is approved only for Deribit')
      select_account(sdk, 'deribit_testnet', testnet_account)
    root = repo_root()
    started = datetime.now(timezone.utc)
    before = capture(root, venue, catalogue)
    typer.echo(f'Checking {venue}: all supported read-only suites…')
    payload = (
      collect(venue, selected, accounts)
      if testnet_account is None
      else collect_deribit(selected, testnet_account, accounts)
    )
    write_report(
      output,
      before=before,
      after=capture(root, venue, catalogue),
      payload=payload,
      started=started,
      finished=datetime.now(timezone.utc),
    )
    typer.echo(f'Recorded {output}; checking release eligibility…')
    verify_payload(payload, root=root)
  except Exception as exception:
    typer.echo(
      f'Not release-verified ({type(exception).__name__}). See the report if recorded.',
      err=True,
    )
    raise typer.Exit(1) from None
  typer.echo('Supported read suites passed; use sdk-dev results verify before release.')
  if testnet_account is not None:
    typer.echo(
      'Deribit: public metadata verified on mainnet; private Report on testnet only.'
    )


@app.command('verify')
def verify(
  report: Path,
  catalogue: Annotated[
    Path, typer.Option(help='Explicit current Catalogue data snapshot.')
  ],
):
  """Verify a report offline; no account configuration or exchange calls are needed."""
  try:
    verify_one(repo_root(), report, catalogue)
  except Exception as exception:
    typer.echo(f'Report rejected: {exception}', err=True)
    raise typer.Exit(1) from None
  typer.echo('Report matches current inputs and satisfies consistency coverage policy.')


def required_venues(root: Path, package: str) -> list[str]:
  """Core requires every shipped implementation, each under its applicable policy."""
  implementations = load_impl_files(root / 'packages' / 'impl')
  venues = sorted(
    venue
    for venue, impl in implementations.items()
    if any(support.support != 'none' for support in impl.support.values())
  )
  if package == 'sdk':
    if not venues:
      raise ValueError('No declared implementations to verify')
    return venues
  if package in venues:
    return [package]
  raise ValueError('No consistency release-evidence policy for this package yet')


def required_scopes(root: Path, venue: str) -> list[Literal['surfaces', 'consistency']]:
  """All packages need read suites; market packages additionally need consistency."""
  impl = load_impl_files(root / 'packages/impl')[venue]
  support = impl.support.get('market')
  return (
    ['surfaces', 'consistency']
    if support is not None and support.support != 'none'
    else ['surfaces']
  )


@app.command('release')
def release(
  package: str,
  catalogue: Annotated[Path, typer.Option(help='Current Catalogue data directory.')],
  reports: Annotated[
    Path, typer.Option(help='Parent of per-venue report directories.')
  ] = Path('release-evidence'),
):
  """Fail closed unless the release candidate has every required matching report."""
  try:
    root = repo_root()
    for venue in required_venues(root, package):
      for scope in required_scopes(root, venue):
        report = reports / venue / scope
        verify_one(root, report, catalogue, venue=venue, scope=scope)
      typer.echo(f'{venue}: verified')
  except Exception as exception:
    typer.echo(f'Release blocked: {exception}', err=True)
    raise typer.Exit(1) from None
