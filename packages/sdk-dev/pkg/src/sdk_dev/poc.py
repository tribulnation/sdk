"""The venue PoCs under `packages/impl/*/poc/` are percent-format scripts: plain Python
where a `# %%` line starts a cell, the format editors run cell-by-cell and jupytext maps
onto a notebook. Outputs never live in the script. `poc run` executes cells into a paired
`.ipynb` next to it, which is gitignored, so what a cell printed against a live account
stays on the machine that ran it.

Pyright reads the scripts as they are, except for two rules a PoC breaks by construction
(cells redefine names across sections, and a trailing bare expression is how a cell
displays a value). So each script is rendered into a scratch copy prefixed with the
pragmas for those, and diagnostics are mapped back through the offset.

Module scope is what a notebook actually has, so the scripts keep it. Wrapping the cells
in an `async def` to legalise top-level `await` would be a worse trade: it demotes every
`X = Literal[...]` to a function-local variable, which pyright rejects as a type alias,
and a PoC would have to be contorted to satisfy the harness. Pyright recovers from
top-level `await` and `async with`/`async for` — it flags them but still infers the types
around them correctly — so `IGNORED` drops those diagnostics instead.

`lint` is the other half of `poc check`: the mechanical rules of the `sdk-poc` skill that
don't need a type checker — no `validate=False`, and, when the paired notebook is there,
no cell left unexecuted without saying why and no stored traceback.
"""

from pathlib import Path
from typing_extensions import Any, NamedTuple, cast
import re

from nbformat import NotebookNode
import jupytext
import nbformat

PRAGMAS = ('# pyright: reportRedeclaration=false, reportUnusedExpression=false',)
IGNORED = (
  '"await" allowed only within async function',
  'Use of "async" not allowed outside of async function',
)
WORKAROUND = re.compile(r'validate\s*=\s*False')
"""Switching validation off hides exactly the typed-client bug a PoC exists to surface."""
NOT_EXECUTED = re.compile(r'#\s*not executed\b', re.IGNORECASE)
"""Marker a cell carries when it is deliberately left unexecuted, with its reason."""
MARKER = re.compile(r'^# %%(?P<rest>.*)$')
"""A percent-format cell marker; `[markdown]` or `[raw]` after it makes the cell non-code."""
NON_CODE = re.compile(r'^\s*\[(markdown|raw)\]')
FORMAT = 'py:percent'


class Cell(NamedTuple):
  """Where one code cell sits in its script."""

  number: int
  """1-based ordinal among the script's code cells."""
  start: int
  """1-based line of the cell's `# %%` marker, or 0 for an unmarked leading cell."""
  end: int
  """1-based line of the cell's last line."""


class Rendered(NamedTuple):
  """A script rendered as type-checkable Python, plus the map back to its cells."""

  source: str
  cells: list[Cell]


class Location(NamedTuple):
  """A diagnostic's position in the script it came from."""

  cell: int
  """1-based code-cell ordinal, or 0 if the line is part of the wrapper."""
  line: int
  """1-based line within that cell, counted from the line after its marker."""


class Finding(NamedTuple):
  """One lint rule a script breaks."""

  cell: int
  """1-based code-cell ordinal."""
  line: int
  """1-based line within that cell."""
  message: str


def read(script: Path) -> NotebookNode:
  """
  Parse a percent-format script into a notebook with no outputs.

  Args:
    script: Path to the `.py` file.

  Raises:
    ValueError: The file can't be parsed as a script.
  """
  try:
    return cast(NotebookNode, jupytext.read(script, fmt=FORMAT))  # pyright: ignore[reportUnknownMemberType]
  except Exception as e:
    raise ValueError(f'{script} is not a readable PoC script: {e}') from e


def code_cells(script: Path) -> list[str]:
  """
  The source of each code cell of a script, in order.

  Args:
    script: Path to the `.py` file.

  Raises:
    ValueError: The file can't be parsed as a script.
  """
  return [cell.source for cell in read(script).cells if cell.cell_type == 'code']


def cells(text: str) -> list[Cell]:
  """
  Where each code cell sits in a script's text.

  A cell runs from its marker to the line before the next marker; anything before the
  first marker is a leading cell without one, which jupytext also treats as code.

  Args:
    text: The script's source.
  """
  lines = text.splitlines()
  starts: list[tuple[int, bool]] = []
  for number, line in enumerate(lines, start=1):
    if (m := MARKER.match(line)) is not None:
      starts.append((number, NON_CODE.match(m['rest']) is None))
  leading = lines[: starts[0][0] - 1] if starts else lines
  if any(line.strip() for line in leading):
    starts.insert(0, (0, True))
  found: list[Cell] = []
  for i, (start, code) in enumerate(starts):
    end = starts[i + 1][0] - 1 if i + 1 < len(starts) else len(lines)
    if code:
      found.append(Cell(number=len(found) + 1, start=start, end=end))
  return found


def render(script: Path) -> Rendered:
  """
  Render a script into a type-checkable copy: the pragmas, then the script verbatim.

  Args:
    script: Path to the `.py` file.
  """
  text = script.read_text()
  offset = len(PRAGMAS)
  shifted = [Cell(c.number, c.start + offset, c.end + offset) for c in cells(text)]
  return Rendered(source='\n'.join((*PRAGMAS, text)), cells=shifted)


def locate(rendered: Rendered, line: int) -> Location:
  """
  Map a 1-based line in the rendered source back to a cell and a line within it.

  Args:
    rendered: The render the line came from.
    line: 1-based line number in `rendered.source`.
  """
  for cell in rendered.cells:
    if cell.start < line <= cell.end:
      return Location(cell=cell.number, line=line - cell.start)
  return Location(cell=0, line=line)


def pair(script: Path) -> Path:
  """
  The notebook `poc run` writes a script's outputs into: the same path with `.ipynb`.

  Args:
    script: Path to the `.py` file.
  """
  return script.with_suffix('.ipynb')


def runs(script: Path) -> list[dict[str, Any]] | None:
  """
  The code cells of a script's paired notebook, or None when it was never run here.

  Args:
    script: Path to the `.py` file.

  Raises:
    ValueError: The pair isn't a readable notebook.
  """
  path = pair(script)
  if not path.is_file():
    return None
  try:
    nb = cast(NotebookNode, nbformat.read(path, as_version=4))  # pyright: ignore[reportUnknownMemberType]
  except Exception as e:
    raise ValueError(f'{path} is not a readable notebook: {e}') from e
  return [cell for cell in nb.cells if cell.cell_type == 'code']


def same(a: str, b: str) -> bool:
  """
  Whether two cell sources are the same code, ignoring trailing whitespace: the percent
  format pads a cell with a blank line that the notebook doesn't keep.

  Args:
    a: One cell's source.
    b: The other's.
  """
  return [line.rstrip() for line in a.rstrip().splitlines()] == [
    line.rstrip() for line in b.rstrip().splitlines()
  ]


def executed(source: str, run: dict[str, Any] | None) -> bool:
  """
  Whether a cell's last run counts: the paired cell holds the same source and has an
  execution count or outputs. A cell edited since it last ran is unexecuted again.

  Args:
    source: The cell's source in the script.
    run: The cell at the same position in the paired notebook, if any.
  """
  if run is None or not same(run.get('source', ''), source):
    return False
  return run.get('execution_count') is not None or bool(run.get('outputs'))


def lint(script: Path) -> list[Finding]:
  """
  Check a script against the PoC rules a type checker can't see.

  `validate=False` is checked in the source. The execution rules need the paired
  notebook: a cell that was never run there must say why with a `# not executed:
  <reason>` line, the way order-placing cells do, and a stored error output means the
  mapping raised when it last ran. Without a pair, a fresh clone, those rules are skipped.

  Args:
    script: Path to the `.py` file.

  Raises:
    ValueError: The script or its pair can't be parsed.
  """
  findings: list[Finding] = []
  ran = runs(script)
  for number, source in enumerate(code_cells(script), start=1):
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
    if ran is None:
      continue
    run = ran[number - 1] if number <= len(ran) else None
    if run is None or not executed(source, run):
      if not NOT_EXECUTED.search(source):
        findings.append(
          Finding(
            number,
            1,
            'never executed: run it with `sdk-dev poc run --cells N`, or mark it '
            '`# not executed: <reason>`',
          )
        )
      continue
    outputs: list[dict[str, Any]] = run.get('outputs') or []
    for output in outputs:
      if output.get('output_type') == 'error':
        findings.append(
          Finding(number, 1, f'raised {output.get("ename")}: {output.get("evalue")}')
        )
  return findings


def scripts(impl_dir: Path, venues: list[str] | None = None) -> list[Path]:
  """
  Find every PoC script under `packages/impl/*/poc/`, recursively.

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
      found += sorted(p for p in poc.rglob('*.py') if '__pycache__' not in p.parts)
  return found


def scratch_name(script: Path, impl_dir: Path) -> str:
  """
  Flatten a script's path into a unique filename for the scratch directory.

  Bitget nests its scripts a level deeper than the other venues, so the venue and
  surface alone don't identify one.

  Args:
    script: Path to the `.py` file.
    impl_dir: The `packages/impl` directory it lives under.
  """
  return '__'.join(script.relative_to(impl_dir).with_suffix('').parts) + '.py'


def parse_cells(spec: str, total: int) -> list[int]:
  """
  Parse a `--cells` selection like `1,3,7-9` into 1-based code-cell ordinals.

  Args:
    spec: Comma-separated ordinals and inclusive `start-end` ranges.
    total: How many code cells the script has, for bounds checking.

  Raises:
    ValueError: The spec is malformed or names a cell the script doesn't have.
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
      raise ValueError(f"{part!r} is outside the script's 1..{total} code cells")
    selected.update(range(start, end + 1))
  if not selected:
    raise ValueError('no cells selected')
  return sorted(selected)
