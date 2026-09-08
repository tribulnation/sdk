"""Script skeletons for a venue PoC: the cells the `sdk-poc` skill expects, with one
cell per method of the SDK surface being mapped and the abstract signature of each
copied from the SDK source, so the script can't drift from the interface it maps. The
skeleton is built as a notebook and written in jupytext's percent format.

Nothing here knows a venue. The surface's methods come from griffe over
`tribulnation.sdk`, the client class name is handed in by the caller, and every body is
`raise NotImplementedError` until the mapping agent replaces it.
"""

from pathlib import Path
from typing_extensions import Any, Literal, NamedTuple, Sequence, cast
import importlib
import re

from nbformat import NotebookNode
import griffe
import jupytext
import nbformat

from sdk_dev.surface import Parameter, parameters, returns, signature, summary

ExchangeKind = Literal['spot', 'perp']


class Surface(NamedTuple):
  """How one SDK surface is scaffolded."""

  module: str
  """Public module whose names the setup cell imports annotation types from."""
  refs: tuple[str, ...]
  """`module.path:Class` of every abstract class the surface is made of."""
  grep: str
  """Starting filter for the surface-discovery cell."""
  collection: str
  """Name of the setup-cell list the calls iterate over."""
  skip: frozenset[str] = frozenset()
  """Methods left out: structural ones that return another SDK object."""


SURFACES: dict[str, Surface] = {
  'earn': Surface(
    module='tribulnation.sdk.earn.instruments',
    refs=('tribulnation.sdk.earn.instruments:Instruments',),
    grep=r'earn|stak|saving|yield|lend|product|subscri',
    collection='ASSETS',
  ),
  'wallet': Surface(
    module='tribulnation.sdk.wallet',
    refs=(
      'tribulnation.sdk.wallet.deposit_methods:DepositMethods',
      'tribulnation.sdk.wallet.withdrawal_methods:WithdrawalMethods',
    ),
    grep=r'deposit|withdraw|coin|currenc|network|chain',
    collection='ASSETS',
  ),
  'report': Surface(
    module='tribulnation.sdk.reporting',
    refs=(
      'tribulnation.sdk.reporting.snapshots:Snapshots',
      'tribulnation.sdk.reporting.history:History',
    ),
    grep=r'balance|account|asset|position|history|ledger|record|fill|transfer|deposit|withdraw',
    collection='ASSETS',
  ),
  'market': Surface(
    module='tribulnation.sdk.market',
    refs=('tribulnation.sdk.market.exchange:PerpExchange',),
    grep=r'orderbook|depth|book|ticker|price|funding|symbol|instrument|contract|order|fill|trade|position|balance',
    collection='MARKETS',
    skip=frozenset({'market'}),
  ),
}
SPOT_EXCHANGE_REF = 'tribulnation.sdk.market.exchange:Exchange'
MUTATING = re.compile(r'^(place|cancel)_')
"""Methods that change account state: scaffolded with their call marked not executed."""
PLACEHOLDERS = {
  'start': 'start',
  'end': 'end',
  'id': "'<order id>'",
  'ids': "['<order id>']",
  'order': "{'type': 'LIMIT', 'qty': Decimal('0'), 'price': Decimal('0')}",
}
"""Arguments for required parameters the scaffold can't know."""
STDLIB_NAMES = {
  'datetime': 'datetime',
  'timedelta': 'datetime',
  'timezone': 'datetime',
  'Decimal': 'decimal',
}
"""Standard-library module each annotation name is imported from."""
TYPING_NAMES = frozenset(
  {
    'Any',
    'AsyncGenerator',
    'AsyncIterable',
    'AsyncIterator',
    'Collection',
    'Iterable',
    'Literal',
    'Mapping',
    'Sequence',
  }
)
BUILTINS = frozenset(
  {'str', 'int', 'bool', 'float', 'None', 'list', 'dict', 'tuple', 'set'}
)
FALLBACK_MODULES = ('tribulnation.sdk.core', 'tribulnation.sdk')
"""Where annotation names are looked up after the surface's own module."""

MethodKind = Literal['call', 'pages', 'stream']


class SurfaceMethod(NamedTuple):
  """One method of an SDK surface, as the scaffold renders it."""

  name: str
  parameters: list[Parameter]
  returns: str | None
  kind: MethodKind
  """`call` awaits a value, `pages` iterates an async iterable, `stream` enters an
  async context manager yielding one."""
  summary: str


def surface_refs(surface: str, exchange: ExchangeKind) -> tuple[str, ...]:
  """
  The abstract classes to scaffold for a surface.

  Args:
    surface: A `SURFACES` key.
    exchange: For `market`, whether to map the spot or the perpetual exchange interface.
  """
  refs = SURFACES[surface].refs
  if surface == 'market' and exchange == 'spot':
    return (SPOT_EXCHANGE_REF,)
  return refs


def surface_methods(
  refs: Sequence[str], *, skip: frozenset[str] = frozenset()
) -> list[SurfaceMethod]:
  """
  The public methods of the given abstract classes, inherited ones included, minus what
  comes from the `SDK` base.

  Args:
    refs: `module.path:Class` references.
    skip: Method names to leave out.
  """
  found: list[SurfaceMethod] = []
  for ref in refs:
    module_path, _, class_name = ref.partition(':')
    module = griffe.load(module_path, docstring_parser='google')
    assert isinstance(module, griffe.Module)
    cls = module[class_name]
    for name, member in cls.all_members.items():
      if name.startswith('_') or name in skip or not member.is_function:
        continue
      fn = member.final_target if isinstance(member, griffe.Alias) else member
      assert isinstance(fn, griffe.Function)
      if fn.parent is None or fn.parent.path.startswith('tribulnation.sdk.core'):
        continue
      if 'property' in fn.labels:
        continue
      if any(m.name == name for m in found):
        continue
      found.append(
        SurfaceMethod(
          name=name,
          parameters=parameters(fn, skip=('self',)),
          returns=returns(fn),
          kind=method_kind(fn),
          summary=summary(fn),
        )
      )
  return found


def method_kind(fn: griffe.Function) -> MethodKind:
  """
  How a method's result is consumed, read off its decorators and return annotation.

  Args:
    fn: The method.
  """
  decorators = {str(d.value) for d in fn.decorators}
  if 'asynccontextmanager' in decorators:
    return 'stream'
  if 'PaginatedResponse.lift' in decorators or str(fn.returns).startswith(
    'AsyncIterable'
  ):
    return 'pages'
  return 'call'


def annotation_names(found: Sequence[SurfaceMethod]) -> set[str]:
  """
  Every identifier used in the methods' annotations, string literals excluded.

  Args:
    found: The surface's methods.
  """
  names: set[str] = set()
  for m in found:
    texts = [p.annotation for p in m.parameters if p.annotation] + (
      [m.returns] if m.returns else []
    )
    for text in texts:
      bare = re.sub(r"'[^']*'|\"[^\"]*\"", '', text)
      names.update(re.findall(r'[A-Za-z_]\w*', bare))
  return names - BUILTINS


def imports_for(
  names: set[str], surface: Surface, refs: Sequence[str] = ()
) -> list[str]:
  """
  Import lines covering `names`: stdlib and typing ones first, then the surface's own
  module, then the modules its abstract classes live in, then the SDK's core and root.

  Args:
    names: Identifiers to import.
    surface: The surface whose module is searched first.
    refs: The `module.path:Class` references whose modules are searched next.
  """
  lines: list[str] = []
  for module_path in sorted({STDLIB_NAMES[n] for n in names if n in STDLIB_NAMES}):
    exported = sorted(n for n in names if STDLIB_NAMES.get(n) == module_path)
    lines.append(f'from {module_path} import {", ".join(exported)}')
  typing = sorted(names & TYPING_NAMES)
  if typing:
    lines.append(f'from typing_extensions import {", ".join(typing)}')
  remaining = sorted(names - set(STDLIB_NAMES) - TYPING_NAMES)
  ref_modules = [ref.partition(':')[0] for ref in refs]
  for module_path in (surface.module, *ref_modules, *FALLBACK_MODULES):
    if not remaining:
      break
    module = importlib.import_module(module_path)
    exported = [n for n in remaining if hasattr(module, n)]
    if exported:
      lines.append(f'from {module_path} import {", ".join(exported)}')
      remaining = [n for n in remaining if n not in exported]
  return lines


def call(method: SurfaceMethod, collection: str) -> str:
  """
  The statement a method's cell ends with, exercising the mapping live.

  Args:
    method: The method.
    collection: The setup-cell list a `market_id` call iterates over.
  """
  args: list[str] = []
  loops = False
  for p in method.parameters:
    if p.default is not None or p.kind.startswith('variadic'):
      continue
    if p.name == 'market_id':
      loops = True
      value = 'market_id'
    else:
      value = PLACEHOLDERS.get(p.name, 'None')
    args.append(f'{p.name}={value}' if p.kind == 'keyword-only' else value)
  expr = f'{method.name}({", ".join(args)})'
  if method.kind == 'stream':
    target = expr.replace('market_id', f'{collection}[0]') if loops else expr
    return f'async with {target} as stream:\n  async for update in stream:\n    print(update)\n    break'
  expr = (
    f'await {expr}' if method.kind == 'call' else f'[record async for record in {expr}]'
  )
  return f'{{market_id: {expr} for market_id in {collection}}}' if loops else expr


def method_cell(method: SurfaceMethod, collection: str) -> str:
  """
  A method's code cell: the abstract signature over an unimplemented body, then its call.

  Args:
    method: The method.
    collection: The setup-cell list a `market_id` call iterates over.
  """
  header = f'async def {method.name}{signature(method.parameters, method.returns)}:'
  body = '  raise NotImplementedError'
  invocation = call(method, collection)
  if MUTATING.match(method.name):
    invocation = f'# not executed: changes the account\n{invocation}'
  return f'{header}\n{body}\n\n\n{invocation}'


def setup_cell(
  surface: Surface,
  found: Sequence[SurfaceMethod],
  *,
  refs: Sequence[str],
  client_module: str,
  client_class: str,
) -> str:
  """
  The first code cell: imports, the client, and the constants the calls draw on.

  Args:
    surface: The surface being mapped.
    found: Its methods, whose annotations decide the imports.
    refs: The abstract classes the methods came from, for import lookup.
    client_module: The typed client package.
    client_class: Its root class.
  """
  names = annotation_names(found)
  needs_window = any(p.name in ('start', 'end') for m in found for p in m.parameters)
  if needs_window:
    names |= {'datetime', 'timedelta', 'timezone'}
  imports = imports_for(names, surface, refs)
  stdlib = [line for line in imports if not line.startswith('from tribulnation')]
  sdk = [line for line in imports if line.startswith('from tribulnation')]
  blocks = [
    '\n'.join(stdlib),
    f'from dotenv import load_dotenv\nfrom {client_module} import {client_class}',
    '\n'.join(sdk),
    f'load_dotenv()\n\nclient = {client_class}.new()',
    f'{surface.collection} = []',
  ]
  if needs_window:
    blocks.append('end = datetime.now(timezone.utc)\nstart = end - timedelta(days=7)')
  return '\n\n'.join(b for b in blocks if b)


def discovery_cell(surface: Surface, *, client_module: str, client_class: str) -> str:
  """
  The cell that lists the client's endpoints, filtered to what the surface could use.

  Args:
    surface: The surface being mapped.
    client_module: The typed client package.
    client_class: Its root class.
  """
  return (
    'from sdk_dev.surface import surface\n\n'
    f"print(surface('{client_module}', '{client_class}', grep=r'{surface.grep}'))"
  )


CATALOGUE_IDS = {
  'earn': (
    'instruments_found = await instruments()\n'
    'ids = Ids(assets={i.asset for i in instruments_found} | '
    '{i.yield_asset for i in instruments_found if i.yield_asset is not None})'
  ),
  'wallet': (
    'methods = [*await deposit_methods(), *await withdrawal_methods()]\n'
    'ids = Ids(assets={m.asset for m in methods}, networks={m.network for m in methods})'
  ),
  'report': (
    'record = await snapshot()\n'
    'ids = Ids(assets=set(record.snapshot.balances), positions=set(record.snapshot.positions))'
  ),
  'market': (
    'listed = await markets()\n'
    'ids = Ids(perp_markets=set(listed))  # spot_markets= for a spot exchange'
  ),
}
"""How each surface's verified results are turned into the IDs the catalogue must
translate."""


def catalogue_cell(surface_name: str, venue: str) -> str:
  """
  The closing code cell: the IDs the surface returned that the catalogue cannot
  translate for this platform, which is the catalogue's to-do list for the venue.

  Args:
    surface_name: A `SURFACES` key.
    venue: The venue slug, also the catalogue platform.
  """
  return (
    'from sdk_dev.catalogue import Ids, gap, load_catalogue\n\n'
    f'{CATALOGUE_IDS[surface_name]}\n'
    f"gap('{venue}', ids, load_catalogue())"
  )


def coverage_cell(found: Sequence[SurfaceMethod]) -> str:
  """
  The closing markdown: one row per method to fill in with its verdict.

  Args:
    found: The surface's methods.
  """
  rows = '\n'.join(f'| `{m.name}` | | |' for m in found)
  return (
    '## Coverage\n\n'
    'Status is one of `verified` (executed live, real data), `empty` (executed live, '
    'nothing to show on this account), `blocked` (a typed-client issue, numbered in '
    '`typed-client-issues.md`), `not supported` (the venue has no such data) or '
    '`not attempted`.\n\n'
    '| method | status | note |\n|---|---|---|\n' + rows
  )


def markdown_cell(source: str) -> dict[str, Any]:
  """
  A notebook markdown cell.

  Args:
    source: The cell text.
  """
  return {'cell_type': 'markdown', 'metadata': {}, 'source': source}


def code_cell(source: str) -> dict[str, Any]:
  """
  A notebook code cell, never executed.

  Args:
    source: The cell text.
  """
  return {
    'cell_type': 'code',
    'metadata': {},
    'source': source,
    'outputs': [],
    'execution_count': None,
  }


def notebook(
  venue: str,
  surface_name: str,
  *,
  client_module: str,
  client_class: str,
  exchange: ExchangeKind = 'perp',
) -> dict[str, Any]:
  """
  Build the PoC notebook for one venue and surface, as nbformat 4 JSON.

  Args:
    venue: The venue slug.
    surface_name: A `SURFACES` key.
    client_module: The typed client package.
    client_class: Its root class.
    exchange: For `market`, whether to map the spot or the perpetual exchange interface.
  """
  surface = SURFACES[surface_name]
  refs = surface_refs(surface_name, exchange)
  found = surface_methods(refs, skip=surface.skip)
  cells = [
    markdown_cell(
      f'# {venue} `{surface_name}` PoC\n\n'
      f'Maps `{client_module}` onto the SDK `{surface_name}` surface, one method per '
      'cell, each executed live. The rules, and how a typed-client issue is reported in '
      '`typed-client-issues.md`, are in `.agents/skills/sdk-poc/SKILL.md`.'
    ),
    code_cell(
      setup_cell(
        surface,
        found,
        refs=refs,
        client_module=client_module,
        client_class=client_class,
      )
    ),
    markdown_cell(
      '## Surface\n\nWhat the client exposes. Widen or narrow the filter until every '
      'endpoint the mapping below uses is listed here.'
    ),
    code_cell(
      discovery_cell(surface, client_module=client_module, client_class=client_class)
    ),
  ]
  for m in found:
    cells.append(markdown_cell(f'## `{m.name}`\n\n{m.summary}'.rstrip()))
    cells.append(code_cell(method_cell(m, surface.collection)))
  cells.append(markdown_cell(coverage_cell(found)))
  cells.append(
    markdown_cell(
      '## Catalogue\n\nEvery ID the verified methods returned, minus what the catalogue '
      'translates for this platform. Anything listed is a catalogue addition to make, '
      'not something to rename here: the SDK emits venue-native IDs and the catalogue '
      'maps them.'
    )
  )
  cells.append(code_cell(catalogue_cell(surface_name, venue)))
  return {'cells': cells, 'metadata': {}, 'nbformat': 4, 'nbformat_minor': 4}


def script_path(poc_dir: Path, surface_name: str, name: str | None) -> Path:
  """
  Where a scaffolded script goes: `poc/<surface>.py`, or `poc/<surface>/<name>.py` when
  a venue needs several scripts for one surface (Bitget's account modes).

  Args:
    poc_dir: The venue's `poc/` directory.
    surface_name: A `SURFACES` key.
    name: The nested script name, if any.
  """
  if name is None:
    return poc_dir / f'{surface_name}.py'
  return poc_dir / surface_name / f'{name}.py'


def write(
  poc_dir: Path,
  venue: str,
  surface_name: str,
  *,
  client_module: str,
  client_class: str,
  name: str | None = None,
  exchange: ExchangeKind = 'perp',
) -> Path:
  """
  Write the scaffolded script, in percent format with no metadata header.

  Args:
    poc_dir: The venue's `poc/` directory, created if missing.
    venue: The venue slug.
    surface_name: A `SURFACES` key.
    client_module: The typed client package.
    client_class: Its root class.
    name: Nest the script as `poc/<surface>/<name>.py`.
    exchange: For `market`, whether to map the spot or the perpetual exchange interface.

  Raises:
    FileExistsError: the script already exists; it is never overwritten.
  """
  path = script_path(poc_dir, surface_name, name)
  if path.exists():
    raise FileExistsError(f'{path} already exists')
  path.parent.mkdir(parents=True, exist_ok=True)
  nb = notebook(
    venue,
    surface_name,
    client_module=client_module,
    client_class=client_class,
    exchange=exchange,
  )
  node = cast(NotebookNode, nbformat.from_dict(nb))  # pyright: ignore[reportUnknownMemberType]
  node.metadata['jupytext'] = {
    'notebook_metadata_filter': '-all',
    'cell_metadata_filter': '-all',
  }
  text = cast(str, jupytext.writes(node, fmt='py:percent'))  # pyright: ignore[reportUnknownMemberType]
  path.write_text(text)
  return path
