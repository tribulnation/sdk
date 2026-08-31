"""CLI entry points for the SDK's docs/contract: validating it (`check`) and syncing it
into a local `landing` checkout (`sync`).
"""

from pathlib import Path
import json
import shutil

import jinja2
import pydantic
import typer
from typing_extensions import Annotated

from sdk_dev.accounts import generate_accounts_toml
from sdk_dev.contract import load_contract_file, render_contract_file
from sdk_dev.schema import generate_schema
from sdk_dev.registry import load_registry
from sdk_dev.repo import CONTRACT_DIR, IMPL_DIR, REGISTRY_PATH, NotACheckout, repo_root
from sdk_dev.support import load_impl_files, load_support_matrix, method_universe

DEFAULT_LANDING_PATH = 'refs/landing'
LANDING_DEST = 'content/docs/sdk/contract'
ACCOUNTS_FILENAME = 'accounts.json'
SCHEMA_FILENAME = 'schema.json'
REGISTRY_FILENAME = 'registry.json'
SUPPORT_FILENAME = 'support.json'


def _build_generated(root: Path) -> dict[str, dict]:
  """
  Validate and render every schema-governed source under `root` into the JSON payloads
  `sync` writes out.

  Each `docs/contract/<stem>.yml` is rendered into `<stem>.json` — its own filename is
  never checked against a hardcoded surface list; whatever `<stem>` is, it's matched
  against every `impl.toml`'s `[support.<stem>]` table (`sdk_dev.support`) to work out,
  per method, which venues it can genuinely be rendered for (that surface's impl.toml
  eligibility, narrowed further to whichever of those venues the method's own `constants`
  actually covers — see `sdk_dev.contract` for the rendering itself).

  Args:
    root: The sdk repo root, from `repo_root()`.

  Returns:
    `{filename: data}` for every generated JSON file — accounts/schema/registry/support,
    plus one `<stem>.json` per `docs/contract/*.yml`.

  Raises:
    pydantic.ValidationError: some source file doesn't match its schema.
    jinja2.TemplateError: a `call`/`result` template doesn't compile, or references a
      fact or catalogue entry that doesn't exist.
  """
  from tribulnation.catalogue import Catalogue

  impl_files = load_impl_files(root / IMPL_DIR)
  catalogue = Catalogue.load()

  generated: dict[str, dict] = {
    ACCOUNTS_FILENAME: generate_accounts_toml(),
    SCHEMA_FILENAME: generate_schema(),
    REGISTRY_FILENAME: load_registry(str(root / REGISTRY_PATH)),
    SUPPORT_FILENAME: load_support_matrix(root / IMPL_DIR),
  }
  for src_file in sorted((root / CONTRACT_DIR).glob('*.yml')):
    surface = src_file.stem
    contract = load_contract_file(src_file)
    universes = {
      name: [
        v
        for v in method_universe(impl_files, surface, name)
        if v in method.example.constants
      ]
      for name, method in contract.methods.items()
    }
    generated[f'{surface}.json'] = render_contract_file(
      contract, universes=universes, catalogue=catalogue
    )
  return generated


def check():
  """
  Validate and render docs/contract/*.yml, registry.toml, and every
  packages/impl/*/impl.toml against their schemas, without syncing anything. Exits
  non-zero on the first schema violation or template error found.
  """
  try:
    root = repo_root()
  except NotACheckout as e:
    typer.echo(
      f'{e}\nRun `sdk-dev docs check` from inside the sdk repo checkout.', err=True
    )
    raise typer.Exit(code=1)

  yml_files = sorted((root / CONTRACT_DIR).glob('*.yml'))
  impl_files = sorted((root / IMPL_DIR).glob('*/impl.toml'))
  try:
    _build_generated(root)
  except (pydantic.ValidationError, jinja2.TemplateError) as e:
    typer.echo(f'{e}', err=True)
    raise typer.Exit(code=1)

  typer.echo(
    f'OK — {len(yml_files)} contract file(s) rendered, registry.toml, '
    f'{len(impl_files)} impl.toml file(s) all valid.'
  )


def sync(
  path: Annotated[
    str | None,
    typer.Option(
      help='Landing checkout to sync into. Defaults to refs/landing relative to the sdk repo root.'
    ),
  ] = None,
):
  """
  Render docs/contract/*.yml + accounts.json/schema.json/registry.json/support.json into
  a local `landing` checkout, for the /sdk docs site.

  Every output file is pure derived data — nothing to hand-maintain, so nothing to
  commit: everything is generated straight into
  <landing>/content/docs/sdk/contract/ on every sync, never written into this repo's own
  docs/contract/ (which stays 100% hand-authored .yml, safe to `git add` wholesale):
    - <stem>.json, one per docs/contract/<stem>.yml (sdk_dev.contract) — every method's
      `call`/`result` (and optional `catalogue` block) rendered once per reachable
      non-empty subset of the venues it can genuinely be called against, so the wizard
      always shows text matching whatever the reader picked. Venue eligibility per
      method comes from every packages/impl/*/impl.toml's `[support.<stem>]` table
      (sdk_dev.support), narrowed to whichever of those venues the method's own `constants`
      covers — a venue only ever reaches the wizard once its package's impl.toml says
      it's ready *and* the method has real illustrative data for it.
    - accounts.json, one `[accounts.<slug>]` TOML block per venue, from the real
      `Account` dataclasses (sdk_dev.accounts) — every field whose *default* is a
      `$ENV_VAR` placeholder is a credential worth showing; everything else (`public`,
      `validate`, ...) isn't. Feeds the wizard's generated sdk.toml.
    - schema.json, the JSON Schema for that same sdk.toml (sdk_dev.schema) — also from
      the real `Account` union, so the two can't disagree with each other.
    - registry.json, from the repo-root registry.toml (sdk_dev.registry) — the hand-
      authored venue list (display name, icon, pypi, tier), mirroring typed-dev's own
      registry.toml/registry.json split.
    - support.json, from every packages/impl/*/impl.toml (sdk_dev.support) — which
      venues offer a given surface at all, and which of those are credential-free
      (`auth: false` in `impl.toml` — a real fact about `DEFAULT_ACCOUNTS`, not derived
      from it, since a venue can have a default account that still needs real
      credentials). Feeds the wizard's sdk.toml generation (skip an entry for a venue
      that's both a public default *and* not required by the current method).

  Every source file is validated and rendered (same schemas as `sdk-dev docs check`)
  before anything is written — an error aborts the sync with nothing written, the
  target checkout's docs untouched.

  Nothing is fetched, committed, or pushed — this only touches the target checkout's
  working tree, left dirty for `yarn dev` to pick up, same as a local (no --publish)
  `typed-dev docs sync`.

  Args:
    path: Landing checkout to sync into. Must already exist and be a real landing
      checkout — this never clones or creates one.
  """
  try:
    root = repo_root()
  except NotACheckout as e:
    typer.echo(
      f'{e}\nRun `sdk-dev docs sync` from inside the sdk repo checkout.', err=True
    )
    raise typer.Exit(code=1)

  landing_root = (
    Path(path).expanduser().resolve()
    if path is not None
    else root / DEFAULT_LANDING_PATH
  )
  if not landing_root.is_dir():
    typer.echo(
      f'{landing_root}: not a directory. Clone `landing` there first, or pass --path.',
      err=True,
    )
    raise typer.Exit(code=1)

  try:
    generated = _build_generated(root)
  except (pydantic.ValidationError, jinja2.TemplateError) as e:
    typer.echo(f'{e}', err=True)
    raise typer.Exit(code=1)

  dest_dir = landing_root / LANDING_DEST
  if dest_dir.is_dir():
    shutil.rmtree(dest_dir)
  dest_dir.mkdir(parents=True)

  for filename, data in generated.items():
    (dest_dir / filename).write_text(json.dumps(data, indent=2) + '\n')

  typer.echo(
    f'Synced {len(generated)} file(s) to {dest_dir.relative_to(landing_root)}: '
    f'{", ".join(sorted(generated))}'
  )
  typer.echo(
    f'\nNext:\n  cd {landing_root}\n  node scripts/render-docs.mjs\n  yarn dev'
  )


app = typer.Typer(
  help="Validating and syncing the SDK's docs/contract into a local landing checkout."
)
app.command('check')(check)
app.command('sync')(sync)
