"""Tests for rendering PoC notebooks into type-checkable Python and mapping pyright's
line numbers back onto cells.
"""

import json
from pathlib import Path
from typing_extensions import Any

import pytest

from sdk_dev.poc import lint, locate, notebooks, parse_cells, render, scratch_name


def write_notebook(path: Path, cells: list[tuple[str, str]]) -> Path:
  """
  Write a minimal notebook of `(cell_type, source)` pairs.

  Args:
    path: Where to write the `.ipynb`.
    cells: The cells, as `('code' | 'markdown', source)` pairs.
  """
  path.write_text(
    json.dumps(
      {
        'cells': [
          {
            'cell_type': kind,
            'metadata': {},
            'source': source.splitlines(keepends=True),
            **({'outputs': [], 'execution_count': None} if kind == 'code' else {}),
          }
          for kind, source in cells
        ],
        'metadata': {},
        'nbformat': 4,
        'nbformat_minor': 5,
      }
    )
  )
  return path


def test_render_keeps_cells_at_module_scope(tmp_path: Path):
  """
  A notebook's cells run at module scope, and the render keeps them there, verbatim.

  Wrapping them in an `async def` to legalise top-level `await` would demote every
  `X = Literal[...]` to a function-local variable, which pyright refuses to treat as a
  type alias — so a notebook would have to be rewritten to satisfy the harness.
  """
  nb = write_notebook(
    tmp_path / 'n.ipynb', [('code', "Currency = Literal['BTC']\nx = await f()")]
  )
  source = render(nb).source
  assert 'async def' not in source
  assert "Currency = Literal['BTC']" in source
  assert 'x = await f()' in source


def test_render_skips_markdown_cells(tmp_path: Path):
  """Only code cells are type-checked, and they keep their relative order."""
  nb = write_notebook(
    tmp_path / 'n.ipynb',
    [('code', 'a = 1'), ('markdown', '# heading'), ('code', 'b = 2')],
  )
  rendered = render(nb)
  assert [c.number for c in rendered.cells] == [1, 2]
  assert 'heading' not in rendered.source


def test_locate_maps_every_line_back_to_its_own_cell(tmp_path: Path):
  """
  Each cell's every line maps back to that cell, at the right offset within it.

  This is what turns a pyright line number into something a reader can act on, and the
  arithmetic is easy to get off by one — so check the whole grid, not a sample.
  """
  sources = ['a = 1\nb = 2\nc = 3', 'd = 4', 'e = 5\nf = 6']
  nb = write_notebook(tmp_path / 'n.ipynb', [('code', s) for s in sources])
  rendered = render(nb)
  lines = rendered.source.splitlines()

  for cell, source in zip(rendered.cells, sources):
    for offset, text in enumerate(source.splitlines()):
      where = locate(rendered, cell.start + offset)
      assert (where.cell, where.line) == (cell.number, offset + 1)
      assert lines[cell.start + offset - 1].strip() == text


def test_locate_reports_wrapper_lines_as_cell_zero(tmp_path: Path):
  """A diagnostic on the generated preamble belongs to no cell."""
  nb = write_notebook(tmp_path / 'n.ipynb', [('code', 'a = 1')])
  assert locate(render(nb), 1).cell == 0


def test_render_rejects_a_file_that_is_not_a_notebook(tmp_path: Path):
  """`poc check` should say so, rather than handing pyright nonsense."""
  bad = tmp_path / 'bad.ipynb'
  bad.write_text('not json')
  with pytest.raises(ValueError):
    render(bad)


@pytest.mark.parametrize(
  ('spec', 'expected'),
  [
    ('1', [1]),
    ('1,3', [1, 3]),
    ('2-4', [2, 3, 4]),
    ('4-5,1', [1, 4, 5]),
    ('1,1,2', [1, 2]),
    (' 1 , 3 ', [1, 3]),
  ],
)
def test_parse_cells_accepts_ordinals_and_ranges(spec: str, expected: list[int]):
  """Selections are deduplicated and sorted, so a run is always in notebook order."""
  assert parse_cells(spec, total=5) == expected


@pytest.mark.parametrize('spec', ['', '0', '6', '3-2', 'x', '1-', '2-9'])
def test_parse_cells_rejects_bad_selections(spec: str):
  """Out-of-range and malformed specs fail loudly, never silently running the wrong cell."""
  with pytest.raises(ValueError):
    parse_cells(spec, total=5)


def test_notebooks_finds_nested_poc_layouts(tmp_path: Path):
  """Bitget nests its notebooks under a surface directory; other venues don't."""
  flat = tmp_path / 'coinbase' / 'poc'
  nested = tmp_path / 'bitget' / 'poc' / 'market'
  for directory in (flat, nested):
    directory.mkdir(parents=True)
  write_notebook(flat / 'market.ipynb', [('code', 'a = 1')])
  write_notebook(nested / 'uta.ipynb', [('code', 'a = 1')])
  (tmp_path / 'kraken').mkdir()

  found = notebooks(tmp_path)
  assert [p.relative_to(tmp_path).as_posix() for p in found] == [
    'bitget/poc/market/uta.ipynb',
    'coinbase/poc/market.ipynb',
  ]
  assert [p.name for p in notebooks(tmp_path, venues=['coinbase'])] == ['market.ipynb']


def test_scratch_name_distinguishes_nested_notebooks(tmp_path: Path):
  """
  Bitget's `market/uta.ipynb` and `wallet/uta.ipynb` share a filename, so the scratch
  name has to carry the whole path or one would overwrite the other.
  """
  impl = tmp_path / 'impl'
  names = {
    scratch_name(impl / 'bitget' / 'poc' / surface / 'uta.ipynb', impl)
    for surface in ('market', 'wallet')
  }
  assert names == {'bitget__poc__market__uta.py', 'bitget__poc__wallet__uta.py'}


def write_cells(path: Path, cells: list[dict[str, Any]]) -> Path:
  """
  Write a notebook of raw code cells, so a test can set outputs and execution counts.

  Args:
    path: Where to write the `.ipynb`.
    cells: Cell dicts; `source` is required, `outputs` and `execution_count` optional.
  """
  path.write_text(
    json.dumps(
      {
        'cells': [
          {
            'cell_type': 'code',
            'metadata': {},
            'source': cell['source'],
            'outputs': cell.get('outputs', []),
            'execution_count': cell.get('execution_count'),
          }
          for cell in cells
        ],
        'metadata': {},
        'nbformat': 4,
        'nbformat_minor': 5,
      }
    )
  )
  return path


def test_lint_rejects_validate_false(tmp_path: Path):
  """Switching validation off hides the typed-client bug the PoC exists to surface."""
  nb = write_cells(
    tmp_path / 'n.ipynb',
    [
      {
        'source': 'x = 1\nraw = await client.get(validate = False)',
        'execution_count': 1,
      }
    ],
  )
  findings = lint(nb)
  assert [(f.cell, f.line) for f in findings] == [(1, 2)]
  assert 'validate=False' in findings[0].message


def test_lint_requires_a_reason_for_an_unexecuted_cell(tmp_path: Path):
  """
  A cell with no execution count and no outputs was never run. Order-placing cells are
  legitimately left that way, and say so with a `# not executed:` line.
  """
  nb = write_cells(
    tmp_path / 'n.ipynb',
    [
      {'source': 'client = make()', 'execution_count': 1},
      {'source': 'await depth()'},
      {'source': '# Not executed -- would place a real order.\nawait place_order()'},
      {'source': 'await rules()', 'outputs': [{'output_type': 'execute_result'}]},
    ],
  )
  assert [f.cell for f in lint(nb)] == [2]
  assert 'never executed' in lint(nb)[0].message


def test_lint_reports_a_stored_traceback(tmp_path: Path):
  """A cell whose last run raised is a broken mapping, whatever else it shows."""
  nb = write_cells(
    tmp_path / 'n.ipynb',
    [
      {
        'source': 'await depth()',
        'execution_count': 3,
        'outputs': [{'output_type': 'error', 'ename': 'KeyError', 'evalue': "'bids'"}],
      }
    ],
  )
  assert [f.message for f in lint(nb)] == ["raised KeyError: 'bids'"]


def test_lint_passes_a_clean_notebook(tmp_path: Path):
  """Executed cells with outputs and marked mutating cells raise nothing."""
  nb = write_cells(
    tmp_path / 'n.ipynb',
    [
      {'source': 'client = make()', 'execution_count': 1},
      {
        'source': 'await depth()',
        'execution_count': 2,
        'outputs': [{'output_type': 'execute_result'}],
      },
      {'source': '# not executed: changes the account\nawait place_order()'},
    ],
  )
  assert lint(nb) == []
