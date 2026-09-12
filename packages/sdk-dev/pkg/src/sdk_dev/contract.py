"""Jinja-templated `docs/contract/*.yml` — one rendering mechanism for every method in
every file, no filename ever hardcoded. `call`/`result` (and the optional `catalogue`
block's own call/result) are Jinja source, not literal Python: `sdk-dev docs sync`
renders each method once per supported venue. The picker can select several packages,
but presents one complete, independently runnable venue example at a time (ADR 0015).

Three globals are available to every template:
  - `accounts`: the singleton list `[venue]` for this rendering.
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

from pathlib import Path
from typing_extensions import Any, Mapping, NotRequired, TypedDict
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


class RenderedSubset(TypedDict):
  """One method rendered for exactly one supported venue."""

  call: str
  """The full runnable script: the component's preamble plus `snippet`."""
  snippet: str
  """The method's own lines alone."""
  result: list[str]
  """The illustrative output, in reveal chunks."""
  catalogueCall: NotRequired[str]
  catalogueResult: NotRequired[str]
  """The `catalogue:` block's call and output, as single static strings."""


class RenderedMethodFlags(TypedDict, total=False):
  """A method's optional metadata, present only when the contract sets it."""

  group: str
  public: bool


class RenderedMethod(RenderedMethodFlags):
  """One method as the /sdk site consumes it."""

  signature: str
  description: str
  semantics: str
  venueNotes: dict[str, str]
  accountVenues: list[str]
  """The method's own initial venue selection."""
  venues: list[str]
  """Every venue the picker offers for this method."""
  subsets: dict[str, RenderedSubset]
  """One example per venue slug; the legacy field name never implies combinations."""


class RenderedContract(TypedDict):
  """One contract file as the /sdk site consumes it, JSON-serializable as-is."""

  component: dict[str, Any]
  methods: dict[str, RenderedMethod]


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
  `universe`'s own order — the order venue examples are generated."""
  ordered = [v for v in preferred if v in universe]
  ordered += [v for v in universe if v not in ordered]
  return ordered


def _render_lines(template: jinja2.Template, ctx: Mapping[str, Any]) -> list[str]:
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
) -> dict[str, RenderedSubset]:
  """
  Render `method`'s templates once per supported venue, with linear output size.

  Args:
    method: The method to render.
    preamble: The component's `preamble` template, rendered ahead of every `call`.
    universe: Every venue this method can genuinely be called against (already narrowed
      to this specific method, not just its surface — see `sdk_dev.support`).
    catalogue: The real, loaded `tribulnation.catalogue.Catalogue`, available to every
      template as the `catalogue` global.

  Returns:
    `{venue: {call, snippet, result, catalogueCall?, catalogueResult?}}` — each
    entry is a complete single-venue script. `result` is a list of reveal
    chunks (for the wizard's staggered "run example" reveal); `catalogueResult`, like the
    primary `call`, is a single rendered string — the catalogue block is shown as one
    static block, never staggered.

  Raises:
    jinja2.TemplateError: a template doesn't compile, or (given `StrictUndefined`)
      references a fact or catalogue entry that doesn't exist.
  """
  missing = sorted(set(universe) - method.example.constants.keys())
  if missing:
    raise ValueError(
      f'missing example constants for supported venues: {", ".join(missing)}'
    )
  invalid = sorted(set(method.example.accountVenues) - set(universe))
  if invalid:
    raise ValueError(f'unsupported default example venues: {", ".join(invalid)}')
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

  rendered: dict[str, RenderedSubset] = {}
  for venue in ordered:
    accounts = [venue]
    ctx: dict[str, Any] = {
      'accounts': accounts,
      'constants': method.example.constants,
      'catalogue': catalogue,
    }
    snippet = call_tpl.render(ctx).strip('\n')
    entry: RenderedSubset = {
      'call': preamble_tpl.render(ctx).strip('\n') + '\n\n' + snippet,
      'snippet': snippet,
      'result': _render_lines(result_tpl, ctx),
    }
    if catalogue_call_tpl is not None and catalogue_result_tpl is not None:
      entry['catalogueCall'] = catalogue_call_tpl.render(ctx).strip('\n')
      # Unlike `result`, the catalogue block is shown as one static block, never a
      # staggered reveal — so its own render stays a single string, no chunk split.
      entry['catalogueResult'] = catalogue_result_tpl.render(ctx).strip('\n')
    rendered[venue] = entry
  return rendered


def render_contract_file(
  contract: ContractFile,
  *,
  universes: dict[str, list[str]],
  catalogue: Any,
  source: dict[str, SourceMethod],
) -> RenderedContract:
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
  methods: dict[str, RenderedMethod] = {}
  for name, method in contract.methods.items():
    flags: RenderedMethodFlags = {}
    if method.group is not None:
      flags['group'] = method.group
    if method.public is not None:
      flags['public'] = method.public
    try:
      examples = render_method(
        method,
        preamble=contract.component.preamble,
        universe=universes[name],
        catalogue=catalogue,
      )
    except ValueError as error:
      raise ValueError(f'{contract.component.title}.{name}: {error}') from error
    methods[name] = {
      **flags,
      **source[name],
      'venueNotes': method.venues,
      'accountVenues': method.example.accountVenues,
      'venues': universes[name],
      'subsets': examples,
    }
  return {
    'component': contract.component.model_dump(
      exclude={'ref', 'preamble'}, exclude_none=True
    ),
    'methods': methods,
  }
