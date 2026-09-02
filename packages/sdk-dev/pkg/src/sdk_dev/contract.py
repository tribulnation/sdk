"""Jinja-templated `docs/contract/*.yml` — one rendering mechanism for every method in
every file, no filename ever hardcoded. `call`/`result` (and the optional `catalogue`
block's own call/result) are Jinja source, not literal Python: `sdk-dev docs sync`
renders each method once per reachable non-empty subset of the venues it can genuinely
be called against, so the wizard always shows text that matches whatever the reader
picked, instead of a single hardcoded combination.

Three globals are available to every template:
  - `accounts`: the venues in this particular rendering, in the method's own preferred
    order (`accountVenues` first, then any other selected venue in registry order) —
    Market's single-active-venue examples just use `accounts[0]`; Earn/Wallet/Report's
    `for venue, sdk in x.all.items()`-shaped examples loop `{% for venue in accounts %}`.
  - `constants`: a `{venue: {...}}` mapping of the illustrative numbers (an APR, a
    balance, a fee) that have no real source to compute from — declared once per venue,
    by the `.yml` author.
  - `catalogue`: the real, loaded `tribulnation.catalogue.Catalogue` — so a translated id
    in a template (`catalogue.asset_translations[venue][constants[venue].asset]`) is computed,
    never hand-typed, and can't silently drift from the real data.

`sdk-dev` doesn't know or care which surface a `.yml` describes — the caller
(`sdk_dev.cli.docs`) is the one that knows, per method, which venues are actually
eligible (from `sdk_dev.support`'s `impl.toml` data) and passes that in as `universe`.
"""

from itertools import combinations
from pathlib import Path
from typing_extensions import Any
import re

import jinja2
import pydantic
import yaml

from sdk_dev.source import SourceMethod

JINJA_ENV = jinja2.Environment(
  trim_blocks=True, lstrip_blocks=True, undefined=jinja2.StrictUndefined
)


class ContractExample(pydantic.BaseModel):
  """A method's `example:` block — Jinja source for the runnable script plus its
  illustrative output, and the per-venue constants those templates draw on."""

  model_config = pydantic.ConfigDict(extra='forbid')

  accountVenues: list[str]
  constants: dict[str, dict[str, Any]] = {}
  callTemplate: str
  resultTemplate: str


class ContractCatalogue(pydantic.BaseModel):
  """A method's optional `catalogue:` block, showing the raw-id-to-canonical-id
  translation — Jinja source, same shape as `ContractExample`'s call/result pair."""

  model_config = pydantic.ConfigDict(extra='forbid')

  callTemplate: str
  resultTemplate: str


class ContractMethod(pydantic.BaseModel):
  """One entry under `methods:`."""

  model_config = pydantic.ConfigDict(extra='forbid')

  group: str | None = None
  ref: str | None = None
  """`module.path:ClassName` overriding the component's `ref` for this one method."""
  public: bool | None = None
  venues: dict[str, str] = {}
  """Per-venue markdown notes, keyed by slug — how this venue's behaviour differs."""
  example: ContractExample
  catalogue: ContractCatalogue | None = None


class ContractComponent(pydantic.BaseModel):
  """The `component:` block — display metadata for the whole file."""

  model_config = pydantic.ConfigDict(extra='forbid')

  title: str
  tagline: str
  preamble: str
  """Jinja source for the lines every example starts with (imports, `load_dotenv()`,
  constructing the SDK). Prepended to each method's `callTemplate` for the wizard's
  runnable script; the docs' method reference shows the call alone."""
  ref: str
  """`module.path:ClassName` whose methods this file documents — signatures and
  docstrings are read from there (`sdk_dev.source`), never written here."""
  note: str | None = None


class ContractFile(pydantic.BaseModel):
  """The full shape of a `docs/contract/*.yml` file."""

  model_config = pydantic.ConfigDict(extra='forbid')

  component: ContractComponent
  methods: dict[str, ContractMethod]


def load_contract_file(path: Path) -> ContractFile:
  """
  Parse and validate one `docs/contract/*.yml` file against `ContractFile`.

  Args:
    path: Path to the `.yml` file.

  Raises:
    pydantic.ValidationError: the file doesn't match `ContractFile`'s shape.
  """
  with open(path) as f:
    raw = yaml.safe_load(f)
  return ContractFile.model_validate(raw)


def _venue_order(preferred: list[str], universe: list[str]) -> list[str]:
  """`preferred` (a method's own `accountVenues`) first, then every other venue in
  `universe`'s own order — the order templates see `accounts` in for any subset."""
  ordered = [v for v in preferred if v in universe]
  ordered += [v for v in universe if v not in ordered]
  return ordered


def _render_lines(template: jinja2.Template, ctx: dict[str, Any]) -> list[str]:
  """
  Render `template` and split it into reveal items — chunks separated by a blank line.

  A chunk's own internal newlines survive intact, so a single multi-line repr (a
  `Rules(...)` block, say) stays one reveal item; a template separates two reveal items
  by emitting a blank line between them (e.g. a loop whose body ends with an extra
  newline, one iteration per venue or per stream tick).
  """
  rendered = template.render(ctx).strip('\n')
  return [
    chunk.strip('\n') for chunk in re.split(r'\n[ \t]*\n', rendered) if chunk.strip()
  ]


def render_method(
  method: ContractMethod, *, preamble: str, universe: list[str], catalogue: Any
) -> dict[str, dict]:
  """
  Render `method`'s templates once per reachable non-empty subset of `universe`.

  Args:
    method: The method to render.
    preamble: The component's `preamble` template, rendered ahead of every `call`.
    universe: Every venue this method can genuinely be called against (already narrowed
      to this specific method, not just its surface — see `sdk_dev.support`).
    catalogue: The real, loaded `tribulnation.catalogue.Catalogue`, available to every
      template as the `catalogue` global.

  Returns:
    `{subset_key: {call, snippet, result, catalogueCall?, catalogueResult?}}` —
    `subset_key` is the selected venues' slugs, sorted and comma-joined, so the frontend
    can compute the same key from whatever it has selected without needing to know this
    function's internal venue ordering. `call` is the full runnable script (preamble plus
    `snippet`); `snippet` is the method's own lines alone. `result` is a list of reveal
    chunks (for the wizard's staggered "run example" reveal); `catalogueResult`, like the
    primary `call`, is a single rendered string — the catalogue block is shown as one
    static block, never staggered.

  Raises:
    jinja2.TemplateError: a template doesn't compile, or (given `StrictUndefined`)
      references a fact or catalogue entry that doesn't exist.
  """
  ordered = _venue_order(method.example.accountVenues, universe)
  preamble_tpl = JINJA_ENV.from_string(preamble)
  call_tpl = JINJA_ENV.from_string(method.example.callTemplate)
  result_tpl = JINJA_ENV.from_string(method.example.resultTemplate)
  catalogue_call_tpl = (
    JINJA_ENV.from_string(method.catalogue.callTemplate) if method.catalogue else None
  )
  catalogue_result_tpl = (
    JINJA_ENV.from_string(method.catalogue.resultTemplate) if method.catalogue else None
  )

  rendered: dict[str, dict] = {}
  for size in range(1, len(ordered) + 1):
    for combo in combinations(ordered, size):
      accounts = list(combo)
      ctx = {
        'accounts': accounts,
        'constants': method.example.constants,
        'catalogue': catalogue,
      }
      snippet = call_tpl.render(ctx).strip('\n')
      entry: dict[str, Any] = {
        'call': preamble_tpl.render(ctx).strip('\n') + '\n\n' + snippet,
        'snippet': snippet,
        'result': _render_lines(result_tpl, ctx),
      }
      if catalogue_call_tpl is not None and catalogue_result_tpl is not None:
        entry['catalogueCall'] = catalogue_call_tpl.render(ctx).strip('\n')
        # Unlike `result`, the catalogue block is shown as one static block, never a
        # staggered reveal — so its own render stays a single string, no chunk split.
        entry['catalogueResult'] = catalogue_result_tpl.render(ctx).strip('\n')
      rendered[','.join(sorted(accounts))] = entry
  return rendered


def render_contract_file(
  contract: ContractFile,
  *,
  universes: dict[str, list[str]],
  catalogue: Any,
  source: dict[str, SourceMethod],
) -> dict:
  """
  Render every method in `contract` into the JSON shape the /sdk site consumes.

  Args:
    contract: A validated `ContractFile`.
    universes: `{method_name: universe}` — every method's eligible-venue list, from
      `sdk_dev.support` (impl.toml), already narrowed to that specific method.
    catalogue: The real, loaded `tribulnation.catalogue.Catalogue`.
    source: `{method_name: SourceMethod}` — each method's signature/description/semantics
      as read from the source by `sdk_dev.source`.

  Returns:
    `{component: {...}, methods: {name: {group, signature, description, semantics,
    public, venueNotes, accountVenues, venues, subsets}}}`, JSON-serializable as-is.
    `venues` is the same list as `universes[name]` (the picker's own options for that
    method); `accountVenues` is the method's own initial/default selection; `subsets` is
    `render_method`'s output.
  """
  return {
    'component': contract.component.model_dump(
      exclude={'ref', 'preamble'}, exclude_none=True
    ),
    'methods': {
      name: {
        **method.model_dump(include={'group', 'public'}, exclude_none=True),
        **source[name],
        'venueNotes': method.venues,
        'accountVenues': method.example.accountVenues,
        'venues': universes[name],
        'subsets': render_method(
          method,
          preamble=contract.component.preamble,
          universe=universes[name],
          catalogue=catalogue,
        ),
      }
      for name, method in contract.methods.items()
    },
  }
