"""CLI entry points for the venue PoC scripts: listing a typed client's endpoints
(`poc surface`), scaffolding a script (`poc scaffold`), type-checking and linting the
scripts (`poc check`) and executing chosen cells against the live venue APIs into the
script's paired notebook (`poc run`).
"""

from pathlib import Path
from typing_extensions import Annotated
import json
import subprocess
import tempfile

import typer

from sdk_dev import scaffold as scaffolding
from sdk_dev.poc import (
  IGNORED,
  PRAGMAS,
  Rendered,
  executed,
  lint,
  locate,
  pair,
  parse_cells,
  read,
  render,
  runs,
  scratch_name,
  scripts,
)
from sdk_dev.repo import IMPL_DIR, NotACheckout, repo_root
from sdk_dev.surface import ClientLookupError, load_client, methods
from sdk_dev.surface import render as render_surface

app = typer.Typer(help='Work with the venue PoC scripts.')


def _diagnostics(root: Path, files: list[Path]) -> list[dict]:
  """
  Run pyright over `files` and return its diagnostics.

  Run from `root` so pyright picks up the repo's `pyrightconfig.json`, which is what
  points it at `.venv` for import resolution.

  Args:
    root: The sdk repo root.
    files: Rendered `.py` files to check.

  Raises:
    RuntimeError: pyright couldn't be run, or returned output that isn't JSON.
  """
  pyright = root / '.venv' / 'bin' / 'pyright'
  try:
    result = subprocess.run(
      [
        str(pyright) if pyright.is_file() else 'pyright',
        '--outputjson',
        *map(str, files),
      ],
      cwd=root,
      capture_output=True,
      text=True,
    )
  except OSError as e:
    raise RuntimeError(f'could not run pyright: {e}') from e
  try:
    return json.loads(result.stdout)['generalDiagnostics']
  except (json.JSONDecodeError, KeyError) as e:
    raise RuntimeError(f'pyright produced no report: {result.stderr.strip()}') from e


@app.command('check')
def check(
  venues: Annotated[
    list[str] | None,
    typer.Argument(help='Venue slugs to check. All venues when omitted.'),
  ] = None,
):
  """
  Type-check and lint every PoC script under `packages/impl/*/poc/`, reporting each
  error against its line and the cell it came from. The execution rules apply to the
  scripts whose paired notebook is present, that is, the ones run on this machine.
  """
  try:
    root = repo_root()
  except NotACheckout as e:
    typer.echo(
      f'{e}\nRun `sdk-dev poc check` from inside the sdk repo checkout.', err=True
    )
    raise typer.Exit(code=1)

  impl_dir = root / IMPL_DIR
  found = scripts(impl_dir, venues)
  if not found:
    typer.echo('No PoC scripts found.', err=True)
    raise typer.Exit(code=1)

  rendered: dict[str, tuple[Path, Rendered]] = {}
  with tempfile.TemporaryDirectory() as tmp:
    scratch = Path(tmp)
    for script in found:
      name = scratch_name(script, impl_dir)
      result = render(script)
      (scratch / name).write_text(result.source)
      rendered[name] = (script, result)

    try:
      diagnostics = _diagnostics(root, sorted(scratch / name for name in rendered))
    except RuntimeError as e:
      typer.echo(f'{e}', err=True)
      raise typer.Exit(code=1)

  errors: dict[str, list[tuple[int, int, str]]] = {name: [] for name in rendered}
  for entry in diagnostics:
    if entry['severity'] != 'error':
      continue
    name = Path(entry['file']).name
    if name not in rendered:
      continue
    message = entry['message'].splitlines()[0]
    if message in IGNORED:
      continue
    where = locate(rendered[name][1], entry['range']['start']['line'] + 1)
    rule = f' ({entry["rule"]})' if entry.get('rule') else ''
    errors[name].append((where.cell, where.line, f'{message}{rule}'))
  unrun = 0
  for name, (script, _) in rendered.items():
    try:
      errors[name] += [(f.cell, f.line, f.message) for f in lint(script)]
    except ValueError as e:
      typer.echo(f'{e}', err=True)
      raise typer.Exit(code=1)
    unrun += not pair(script).is_file()

  total = 0
  for name, (script, result) in rendered.items():
    markers = {c.number: c.start - len(PRAGMAS) for c in result.cells}
    found_errors = [
      (markers.get(cell, -len(PRAGMAS)) + line, f'cell {cell}, line {line}: {message}')
      for cell, line, message in sorted(errors[name])
    ]
    total += len(found_errors)
    if found_errors:
      typer.echo(f'{script.relative_to(root)}')
      for at, message in sorted(found_errors):
        typer.echo(f'  L{at} {message}')

  checked = f'{len(rendered)} script{"" if len(rendered) == 1 else "s"}'
  if unrun:
    typer.echo(f'{unrun} of {checked} never run here; execution rules not checked.')
  if total:
    typer.echo(f'\n{total} error{"" if total == 1 else "s"} in {checked}.')
    raise typer.Exit(code=1)
  typer.echo(f'{checked} clean.')


def resolve_client(venue: str, client: str | None) -> tuple[str, str]:
  """
  The typed client package and root class for a venue: `typed_<venue>` and the class
  its `main` module defines, unless `client` names them as `module:Class`.

  Args:
    venue: The venue slug.
    client: An explicit `module:Class`, or just `module`.

  Raises:
    ClientLookupError: the package or class can't be found.
  """
  module, _, class_name = (client or f'typed_{venue}').partition(':')
  _, cls = load_client(module, class_name or None)
  return module, cls.name


CLIENT_HELP = (
  'Typed client as `module:Class`, when it is not `typed_<venue>` with a single root '
  'class in its `main` module — e.g. `typed_alchemy:Alchemy` for ethereum.'
)


@app.command('surface')
def surface(
  venue: Annotated[str, typer.Argument(help='Venue slug, e.g. `bitget`.')],
  paths: Annotated[
    list[str] | None,
    typer.Argument(
      help='Dotted namespaces to list, e.g. `classic.mix.market`. All when omitted.'
    ),
  ] = None,
  grep: Annotated[
    str | None,
    typer.Option(
      '--grep', help='Keep endpoints whose path or summary matches this regex.'
    ),
  ] = None,
  client: Annotated[str | None, typer.Option('--client', help=CLIENT_HELP)] = None,
):
  """
  List every endpoint a venue's typed client exposes, with its path from the client
  root, signature and one-line summary — the menu a PoC maps from.
  """
  try:
    module, class_name = resolve_client(venue, client)
    _, cls = load_client(module, class_name)
  except ClientLookupError as e:
    typer.echo(f'{e}', err=True)
    raise typer.Exit(code=1)
  typer.echo(render_surface(methods(cls, module), paths=paths or (), grep=grep))


@app.command('scaffold')
def scaffold(
  venue: Annotated[str, typer.Argument(help='Venue slug, e.g. `bitget`.')],
  surface: Annotated[
    str,
    typer.Argument(help=f'SDK surface: one of {", ".join(scaffolding.SURFACES)}.'),
  ],
  name: Annotated[
    str | None,
    typer.Option(
      '--name',
      help='Nest the script as `poc/<surface>/<name>.py`, for venues that need one '
      'script per account mode.',
    ),
  ] = None,
  exchange: Annotated[
    str,
    typer.Option(
      '--exchange',
      help='For `market`: map the `spot` or the `perp` exchange interface.',
    ),
  ] = 'perp',
  client: Annotated[str | None, typer.Option('--client', help=CLIENT_HELP)] = None,
):
  """
  Write a PoC script skeleton for one venue and surface, one cell per abstract method
  with its signature copied from the SDK.
  """
  if surface not in scaffolding.SURFACES:
    typer.echo(
      f'{surface!r} is not a surface: {", ".join(scaffolding.SURFACES)}.', err=True
    )
    raise typer.Exit(code=1)
  if exchange not in ('spot', 'perp'):
    typer.echo(f'--exchange must be `spot` or `perp`, not {exchange!r}.', err=True)
    raise typer.Exit(code=1)
  try:
    root = repo_root()
    module, class_name = resolve_client(venue, client)
    path = scaffolding.write(
      root / IMPL_DIR / venue / 'poc',
      venue,
      surface,
      client_module=module,
      client_class=class_name,
      name=name,
      exchange=exchange,
    )
  except (NotACheckout, ClientLookupError, FileExistsError) as e:
    typer.echo(f'{e}', err=True)
    raise typer.Exit(code=1)
  typer.echo(f'{path.relative_to(root)}')


@app.command('run')
def run(
  script: Annotated[Path, typer.Argument(help='Path to the PoC `.py` script.')],
  cells: Annotated[
    str,
    typer.Option(
      '--cells',
      help='Which code cells to execute, 1-based: e.g. "1,3,7-9". Required — there is '
      'no run-everything shorthand, because PoC scripts hold order-placing cells that '
      'must not fire against a live account.',
    ),
  ],
  timeout: Annotated[int, typer.Option(help='Per-cell timeout in seconds.')] = 120,
):
  """
  Execute selected code cells against the live venue API and store their outputs in
  the script's paired notebook, `<script>.ipynb`, which is gitignored.

  Every selected cell runs in one kernel session, in script order, so cells may build
  on names the earlier ones defined. Cells that aren't selected keep the outputs of
  their last run, as long as their source hasn't changed since.
  """
  import nbformat
  from nbclient import NotebookClient
  from nbclient.exceptions import CellExecutionError

  if not script.is_file():
    typer.echo(f'{script}: no such script.', err=True)
    raise typer.Exit(code=1)
  if script.suffix != '.py':
    typer.echo(
      f'{script}: PoCs are `.py` scripts; `poc run` writes the `.ipynb`.', err=True
    )
    raise typer.Exit(code=1)

  try:
    nb = read(script)
    previous = runs(script) or []
  except ValueError as e:
    typer.echo(f'{e}', err=True)
    raise typer.Exit(code=1)
  code = [i for i, cell in enumerate(nb.cells) if cell.cell_type == 'code']
  for number, index in enumerate(code):
    run = previous[number] if number < len(previous) else None
    if executed(nb.cells[index].source, run) and run is not None:
      nb.cells[index].outputs = run.get('outputs', [])
      nb.cells[index].execution_count = run.get('execution_count')
  try:
    selected = parse_cells(cells, len(code))
  except ValueError as e:
    typer.echo(f'{e}.', err=True)
    raise typer.Exit(code=1)

  client = NotebookClient(
    nb,
    timeout=timeout,
    kernel_name='python3',
    allow_errors=True,
    resources={'metadata': {'path': str(script.parent)}},
  )
  failed: list[int] = []
  with client.setup_kernel():
    for number in selected:
      index = code[number - 1]
      typer.echo(f'cell {number} ... ', nl=False)
      try:
        client.execute_cell(nb.cells[index], index)
      except CellExecutionError as e:
        typer.echo(f'error: {e}')
        failed.append(number)
        continue
      errors = [
        o for o in nb.cells[index].get('outputs', []) if o.get('output_type') == 'error'
      ]
      if errors:
        typer.echo(f'{errors[0].get("ename")}: {errors[0].get("evalue")}')
        failed.append(number)
      else:
        typer.echo('ok')

  nbformat.write(nb, pair(script))  # pyright: ignore[reportUnknownMemberType]
  ran = f'{len(selected)} cell{"" if len(selected) == 1 else "s"}'
  if failed:
    typer.echo(f'\n{ran} run, {len(failed)} raised: {", ".join(map(str, failed))}.')
    raise typer.Exit(code=1)
  typer.echo(f'\n{ran} run clean.')
