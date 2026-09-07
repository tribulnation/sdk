"""Renders the venue PoC notebooks under `packages/impl/*/poc/` into plain Python so
pyright can type-check them, and maps the diagnostics it reports back onto cells.

Pyright's CLI has no notebook support — handed a `.ipynb` it parses the JSON as Python
and fails on `null`. So each notebook is rendered into an equivalent `.py`: code cells
concatenated in order at module scope, verbatim, prefixed only by the pragmas for the
two rules a notebook breaks by construction (cells redefine names across sections, and a
trailing bare expression is how a cell displays a value).

Module scope is what a notebook actually has, so the render keeps it. Wrapping the cells
in an `async def` to legalise top-level `await` would be a worse trade: it demotes every
`X = Literal[...]` to a function-local variable, which pyright rejects as a type alias,
and a notebook would have to be contorted to satisfy the harness. Pyright recovers from
top-level `await` and `async with`/`async for` — it flags them but still infers the types
around them correctly — so `IGNORED` drops those diagnostics instead.

`lint` is the other half of `poc check`: the mechanical rules of the `sdk-poc` skill that
don't need a type checker — no `validate=False`, no cell left unexecuted without saying
why, no stored traceback.
"""

from pathlib import Path
from typing_extensions import Any, NamedTuple
import json
import re

PRAGMAS = ('# pyright: reportRedeclaration=false, reportUnusedExpression=false',)
IGNORED = (
  '"await" allowed only within async function',
  'Use of "async" not allowed outside of async function',
)
WORKAROUND = re.compile(r'validate\s*=\s*False')
"""Switching validation off hides exactly the typed-client bug a PoC exists to surface."""
NOT_EXECUTED = re.compile(r'#\s*not executed\b', re.IGNORECASE)
"""Marker a cell carries when it is deliberately left unexecuted, with its reason."""


class Cell(NamedTuple):
  """Where one code cell landed in the rendered source."""

  number: int
  """1-based ordinal among the notebook's code cells."""
  start: int
  """1-based line of the cell's first line in the rendered source."""
  length: int
  """Line count of the cell."""


class Rendered(NamedTuple):
  """A notebook rendered as type-checkable Python, plus the map back to its cells."""

  source: str
  cells: list[Cell]


class Location(NamedTuple):
  """A diagnostic's position in the notebook it came from."""

  cell: int
  """1-based code-cell ordinal, or 0 if the line is part of the wrapper."""
  line: int
  """1-based line within that cell."""


class Finding(NamedTuple):
  """One lint rule a notebook breaks."""

  cell: int
  """1-based code-cell ordinal."""
  line: int
  """1-based line within that cell."""
  message: str


def code_cells(notebook: Path) -> list[dict[str, Any]]:
  """
  A notebook's code cells, in order.

  Args:
    notebook: Path to the `.ipynb` file.

  Raises:
    ValueError: The file isn't valid notebook JSON.
  """
  try:
    data = json.loads(notebook.read_text())
    return [cell for cell in data['cells'] if cell['cell_type'] == 'code']
  except (json.JSONDecodeError, KeyError, TypeError) as e:
    raise ValueError(f'{notebook} is not a readable notebook: {e}') from e


def render(notebook: Path) -> Rendered:
  """
  Render a notebook's code cells into a single type-checkable Python source.

  Args:
    notebook: Path to the `.ipynb` file.

  Raises:
    ValueError: The file isn't valid notebook JSON.
  """
  raw = [''.join(cell['source']) for cell in code_cells(notebook)]
  cells: list[Cell] = []
  lines: list[str] = list(PRAGMAS)
  for number, source in enumerate(raw, start=1):
    if cells:
      lines.append('')
    body = source.splitlines() or ['']
    cells.append(Cell(number=number, start=len(lines) + 1, length=len(body)))
    lines += body

  return Rendered(source='\n'.join((*lines, '')), cells=cells)


def locate(rendered: Rendered, line: int) -> Location:
  """
  Map a 1-based line in the rendered source back to a cell and a line within it.

  Args:
    rendered: The render the line came from.
    line: 1-based line number in `rendered.source`.
  """
  for cell in rendered.cells:
    if cell.start <= line < cell.start + cell.length:
      return Location(cell=cell.number, line=line - cell.start + 1)
  return Location(cell=0, line=line)


def lint(notebook: Path) -> list[Finding]:
  """
  Check a notebook against the PoC rules a type checker can't see.

  A cell counts as executed when it has an execution count or outputs; one that has
  neither must say why with a `# not executed: <reason>` line, the way order-placing
  cells do. A stored error output means the mapping raised when it last ran.

  Args:
    notebook: Path to the `.ipynb` file.

  Raises:
    ValueError: The file isn't valid notebook JSON.
  """
  findings: list[Finding] = []
  for number, cell in enumerate(code_cells(notebook), start=1):
    source = ''.join(cell.get('source', ''))
    for line_number, line in enumerate(source.splitlines(), start=1):
      if WORKAROUND.search(line):
        findings.append(
          Finding(
            number,
            line_number,
            'validate=False: a validation failure is a typed-client issue to record in '
            'typed-client-issues.md, not something to switch off',
          )
        )
    outputs: list[dict[str, Any]] = cell.get('outputs') or []
    executed = cell.get('execution_count') is not None or bool(outputs)
    if not executed and not NOT_EXECUTED.search(source):
      findings.append(
        Finding(
          number,
          1,
          'never executed: run it with `sdk-dev poc run --cells N`, or mark it '
          '`# not executed: <reason>`',
        )
      )
    for output in outputs:
      if output.get('output_type') == 'error':
        findings.append(
          Finding(number, 1, f'raised {output.get("ename")}: {output.get("evalue")}')
        )
  return findings


def notebooks(impl_dir: Path, venues: list[str] | None = None) -> list[Path]:
  """
  Find every PoC notebook under `packages/impl/*/poc/`, recursively.

  Args:
    impl_dir: The `packages/impl` directory.
    venues: Restrict to these venue slugs. All venues when omitted.
  """
  found: list[Path] = []
  for venue in sorted(impl_dir.iterdir()):
    if not venue.is_dir() or (venues is not None and venue.name not in venues):
      continue
    poc = venue / 'poc'
    if poc.is_dir():
      found += sorted(
        p for p in poc.rglob('*.ipynb') if '.ipynb_checkpoints' not in p.parts
      )
  return found


def scratch_name(notebook: Path, impl_dir: Path) -> str:
  """
  Flatten a notebook's path into a unique `.py` filename for the scratch directory.

  Bitget nests its notebooks a level deeper than the other venues, so the venue and
  surface alone don't identify one.

  Args:
    notebook: Path to the `.ipynb` file.
    impl_dir: The `packages/impl` directory it lives under.
  """
  return '__'.join(notebook.relative_to(impl_dir).with_suffix('').parts) + '.py'


def parse_cells(spec: str, total: int) -> list[int]:
  """
  Parse a `--cells` selection like `1,3,7-9` into 1-based code-cell ordinals.

  Args:
    spec: Comma-separated ordinals and inclusive `start-end` ranges.
    total: How many code cells the notebook has, for bounds checking.

  Raises:
    ValueError: The spec is malformed or names a cell the notebook doesn't have.
  """
  selected: set[int] = set()
  for part in spec.split(','):
    part = part.strip()
    if not part:
      continue
    try:
      if '-' in part.lstrip('-'):
        start, end = (int(x) for x in part.split('-', 1))
      else:
        start = end = int(part)
    except ValueError:
      raise ValueError(f'{part!r} is not a cell number or range') from None
    if start > end:
      raise ValueError(f'{part!r} is an empty range')
    if start < 1 or end > total:
      raise ValueError(f"{part!r} is outside the notebook's 1..{total} code cells")
    selected.update(range(start, end + 1))
  if not selected:
    raise ValueError('no cells selected')
  return sorted(selected)
