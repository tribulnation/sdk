"""Tests for rendering PoC scripts into type-checkable Python, mapping pyright's line
numbers back onto cells, and the lint rules against the paired notebook.
"""

import json
from pathlib import Path
from typing_extensions import Any

import pytest

from sdk_dev.poc import (
  cells,
  code_cells,
  lint,
  locate,
  pair,
  parse_cells,
  read,
  render,
  scratch_name,
  scripts,
)


def write_script(path: Path, blocks: list[tuple[str, str]]) -> Path:
  """
  Write a percent-format script of `(cell_type, source)` pairs.

  Args:
    path: Where to write the `.py`.
    blocks: The cells, as `('code' | 'markdown', source)` pairs.
  """
  rendered: list[str] = []
  for kind, source in blocks:
    if kind == 'markdown':
      body = '\n'.join(f'# {line}'.rstrip() for line in source.splitlines())
      rendered.append(f'# %% [markdown]\n{body}')
    else:
      rendered.append(f'# %%\n{source}')
  path.write_text('\n\n'.join(rendered) + '\n')
  return path


def write_pair(script: Path, runs: list[dict[str, Any]]) -> Path:
  """
  Write the notebook `poc run` would have left beside a script.

  Args:
    script: The `.py` the notebook pairs with.
    runs: Code cells; `source` is required, `outputs` and `execution_count` optional.
  """
  path = pair(script)
  path.write_text(
    json.dumps(
      {
        'cells': [
          {
            'cell_type': 'code',
            'metadata': {},
            'source': run['source'],
            'outputs': run.get('outputs', []),
            'execution_count': run.get('execution_count'),
          }
          for run in runs
        ],
        'metadata': {},
        'nbformat': 4,
        'nbformat_minor': 4,
      }
    )
  )
  return path


def test_render_keeps_cells_at_module_scope(tmp_path: Path):
  """
  A script's cells run at module scope, and the render keeps them there, verbatim.

  Wrapping them in an `async def` to legalise top-level `await` would demote every
  `X = Literal[...]` to a function-local variable, which pyright refuses to treat as a
  type alias — so a script would have to be rewritten to satisfy the harness.
  """
  script = write_script(
    tmp_path / 'n.py', [('code', "Currency = Literal['BTC']\nx = await f()")]
  )
  source = render(script).source
  assert 'async def' not in source
  assert source.startswith('# pyright:')
  assert source.endswith(script.read_text())


def test_read_parses_markdown_and_code_cells(tmp_path: Path):
  """Markdown blocks are cells too, and don't count as code."""
  script = write_script(
    tmp_path / 'n.py',
    [('markdown', '## Title\n\nProse.'), ('code', 'a = 1'), ('code', 'b = 2')],
  )
  kinds = [cell['cell_type'] for cell in read(script)['cells']]
  assert kinds == ['markdown', 'code', 'code']
  assert code_cells(script) == ['a = 1', 'b = 2']


def test_cells_span_marker_to_next_marker(tmp_path: Path):
  """A code cell owns the lines from its `# %%` to the line before the next marker."""
  text = '# %%\na = 1\nb = 2\n\n# %% [markdown]\n# ## Title\n\n# %%\nc = 3\n'
  assert [(c.number, c.start, c.end) for c in cells(text)] == [(1, 1, 4), (2, 8, 9)]


def test_cells_count_an_unmarked_leading_cell(tmp_path: Path):
  """Text before the first marker is a cell without one; jupytext reads it as code."""
  script = tmp_path / 'n.py'
  script.write_text('x = 1\n\n# %%\ny = 2\n')
  assert [(c.number, c.start, c.end) for c in cells(script.read_text())] == [
    (1, 0, 2),
    (2, 3, 4),
  ]
  assert code_cells(script) == ['x = 1', 'y = 2']


def test_locate_maps_every_line_back_to_its_own_cell(tmp_path: Path):
  """Each rendered line resolves to the cell it came from and its line within it."""
  script = write_script(
    tmp_path / 'n.py',
    [('code', 'a = 1\nb = 2'), ('markdown', '## Title'), ('code', 'c = 3')],
  )
  rendered = render(script)
  lines = rendered.source.splitlines()
  assert lines[0].startswith('# pyright:')
  assert locate(rendered, lines.index('a = 1') + 1) == (1, 1)
  assert locate(rendered, lines.index('b = 2') + 1) == (1, 2)
  assert locate(rendered, lines.index('c = 3') + 1) == (2, 1)


def test_locate_reports_wrapper_lines_as_cell_zero(tmp_path: Path):
  """The pragma line, markers and markdown belong to no code cell."""
  script = write_script(
    tmp_path / 'n.py', [('code', 'a = 1'), ('markdown', '## Title'), ('code', 'b = 2')]
  )
  rendered = render(script)
  lines = rendered.source.splitlines()
  assert locate(rendered, 1) == (0, 1)
  assert locate(rendered, lines.index('# %% [markdown]') + 1).cell == 0
  assert locate(rendered, lines.index('# ## Title') + 1).cell == 0


def test_read_rejects_a_missing_script(tmp_path: Path):
  """A path that isn't there is a `ValueError`, not a traceback from jupytext."""
  with pytest.raises(ValueError, match='not a readable PoC script'):
    read(tmp_path / 'missing.py')


@pytest.mark.parametrize(
  'spec, expected',
  [('1', [1]), ('1,3', [1, 3]), ('7-9', [7, 8, 9]), ('1, 3-4, 9', [1, 3, 4, 9])],
)
def test_parse_cells_accepts_ordinals_and_ranges(spec: str, expected: list[int]):
  """Selections are ordinals and inclusive ranges, whitespace-tolerant."""
  assert parse_cells(spec, total=9) == expected


@pytest.mark.parametrize('spec', ['', '0', '10', 'a', '3-1', '5-'])
def test_parse_cells_rejects_bad_selections(spec: str):
  """Out-of-range, malformed and empty selections are refused."""
  with pytest.raises(ValueError):
    parse_cells(spec, total=9)


def test_scripts_finds_nested_poc_layouts(tmp_path: Path):
  """Bitget nests its scripts under a surface directory; other venues don't."""
  flat = tmp_path / 'coinbase' / 'poc'
  nested = tmp_path / 'bitget' / 'poc' / 'market'
  for directory in (flat, nested):
    directory.mkdir(parents=True)
  write_script(flat / 'market.py', [('code', 'a = 1')])
  write_script(nested / 'uta.py', [('code', 'a = 1')])
  write_pair(flat / 'market.py', [{'source': 'a = 1'}])
  (tmp_path / 'kraken').mkdir()

  found = scripts(tmp_path)
  assert [p.relative_to(tmp_path).as_posix() for p in found] == [
    'bitget/poc/market/uta.py',
    'coinbase/poc/market.py',
  ]
  assert [p.name for p in scripts(tmp_path, venues=['coinbase'])] == ['market.py']


def test_scratch_name_distinguishes_nested_scripts(tmp_path: Path):
  """
  Bitget's `market/uta.py` and `wallet/uta.py` share a filename, so the scratch name
  has to carry the whole path or one would overwrite the other.
  """
  impl = tmp_path / 'impl'
  names = {
    scratch_name(impl / 'bitget' / 'poc' / surface / 'uta.py', impl)
    for surface in ('market', 'wallet')
  }
  assert names == {'bitget__poc__market__uta.py', 'bitget__poc__wallet__uta.py'}


def test_lint_rejects_validate_false(tmp_path: Path):
  """Switching validation off hides the typed-client bug the PoC exists to surface."""
  script = write_script(
    tmp_path / 'n.py', [('code', 'x = 1\nraw = await client.get(validate = False)')]
  )
  findings = lint(script)
  assert [(f.cell, f.line) for f in findings] == [(1, 2)]
  assert 'validate=False' in findings[0].message


def test_lint_skips_the_execution_rules_without_a_pair(tmp_path: Path):
  """A fresh clone has no run record, so unexecuted cells can't be held against it."""
  script = write_script(tmp_path / 'n.py', [('code', 'await depth()')])
  assert lint(script) == []


def test_lint_requires_a_reason_for_an_unexecuted_cell(tmp_path: Path):
  """
  A cell with no execution count and no outputs in the pair was never run.
  Order-placing cells are legitimately left that way, and say so with a
  `# not executed:` line.
  """
  script = write_script(
    tmp_path / 'n.py',
    [
      ('code', 'client = make()'),
      ('code', 'await depth()'),
      ('code', '# Not executed -- would place a real order.\nawait place_order()'),
      ('code', 'await rules()'),
    ],
  )
  write_pair(
    script,
    [
      {'source': 'client = make()', 'execution_count': 1},
      {'source': 'await depth()'},
      {'source': '# Not executed -- would place a real order.\nawait place_order()'},
      {'source': 'await rules()', 'outputs': [{'output_type': 'execute_result'}]},
    ],
  )
  assert [f.cell for f in lint(script)] == [2]
  assert 'never executed' in lint(script)[0].message


def test_lint_treats_an_edited_cell_as_unexecuted(tmp_path: Path):
  """A cell changed since its last run has outputs that no longer prove anything."""
  script = write_script(
    tmp_path / 'n.py', [('code', 'await depth()'), ('code', 'await rules(fresh=True)')]
  )
  write_pair(
    script,
    [
      {'source': 'await depth()', 'execution_count': 1},
      {'source': 'await rules()', 'execution_count': 2},
    ],
  )
  assert [f.cell for f in lint(script)] == [2]


def test_lint_ignores_trailing_whitespace_in_the_pair(tmp_path: Path):
  """The percent format pads cells with blank lines the notebook never stored."""
  script = write_script(tmp_path / 'n.py', [('code', 'await depth()\n\n')])
  write_pair(script, [{'source': 'await depth()', 'execution_count': 1}])
  assert lint(script) == []


def test_lint_reports_a_stored_traceback(tmp_path: Path):
  """A cell whose last run raised is a broken mapping, whatever else it shows."""
  script = write_script(tmp_path / 'n.py', [('code', 'await depth()')])
  write_pair(
    script,
    [
      {
        'source': 'await depth()',
        'execution_count': 3,
        'outputs': [{'output_type': 'error', 'ename': 'KeyError', 'evalue': "'bids'"}],
      }
    ],
  )
  assert [f.message for f in lint(script)] == ["raised KeyError: 'bids'"]


def test_lint_passes_a_clean_script(tmp_path: Path):
  """Executed cells with outputs and marked mutating cells raise nothing."""
  script = write_script(
    tmp_path / 'n.py',
    [
      ('code', 'client = make()'),
      ('code', 'await depth()'),
      ('code', '# not executed: changes the account\nawait place_order()'),
    ],
  )
  write_pair(
    script,
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
  assert lint(script) == []
