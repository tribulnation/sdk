"""CLI entry point for inspecting the /sdk support matrix — the venue x surface grid
declared across every packages/impl/*/impl.toml, exactly what `sdk-dev docs sync` turns
into support.json for the wizard.
"""

import typer

from sdk_dev.repo import IMPL_DIR, NotACheckout, repo_root
from sdk_dev.support import load_impl_files


def support():
  """
  Print the full venue x surface support matrix, grouped by surface, from every
  packages/impl/*/impl.toml.
  """
  try:
    root = repo_root()
  except NotACheckout as e:
    typer.echo(
      f'{e}\nRun `sdk-dev support` from inside the sdk repo checkout.', err=True
    )
    raise typer.Exit(code=1)

  impls = load_impl_files(root / IMPL_DIR)
  surfaces = sorted({surface for data in impls.values() for surface in data.support})

  for surface in surfaces:
    typer.echo(f'{surface}:')
    for slug, data in sorted(impls.items()):
      entry = data.support.get(surface)
      if entry is None:
        continue
      auth = 'auth' if entry.auth else 'no auth'
      methods = f' ({", ".join(entry.methods)})' if entry.methods else ''
      typer.echo(f'  {slug:<12} {entry.support}{methods}, {auth}')
    typer.echo()
