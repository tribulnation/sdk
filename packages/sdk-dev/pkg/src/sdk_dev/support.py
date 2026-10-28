"""Aggregates every `packages/impl/*/impl.toml` into a per-surface support matrix —
which venues offer a given surface (`supportedVenues`) and which of those work with a
credential-free `public = true` account (`defaultVenues`, from `auth = false`; the name
predates the removal of SDK default accounts and is kept for the site). This is what the /sdk
wizard's venue picker and sdk.toml generation are driven by, so a venue only ever shows up
there once its own package's impl.toml says it's ready — never derived from router code
alone (a venue can be wired into an *SDK's router ahead of being ready to announce; see
any impl.toml's own comments for real examples of that gate in use).
"""

from collections.abc import Mapping
from pathlib import Path
import tomllib

import pydantic
import yaml
from typing_extensions import Literal, NotRequired, TypedDict

MarketKind = Literal['spot', 'perp']
"""A kind of market (ADR 0051). A contract method with a `kind` exists only on markets
of that kind; a venue's `kinds` says which of them it serves (ADR 0056)."""


class ImplSurfaceSupport(pydantic.BaseModel):
  """One `[support.<surface>]` table in a package's `impl.toml`."""

  model_config = pydantic.ConfigDict(extra='forbid')

  support: Literal['full', 'partial', 'none']
  """`none` announces a deliberate gap: the venue is excluded from the surface exactly as
  if the table were absent, but its `note` still reaches the support matrix. `full`
  means every contract method applicable to `kinds`."""
  auth: bool
  kinds: list[MarketKind] | None = pydantic.Field(default=None, min_length=1)
  """Market kinds the venue serves (ADR 0056). A method whose contract `kind` is not
  among them does not apply to the venue. Absent means every kind; only surfaces with
  kind-scoped methods (Market) may set it."""
  methods: list[str] | None = None
  note: str | None = None
  """One user-facing sentence rendered as a footnote under the support matrix — a caveat
  the data alone can't express (a module that exists but isn't wired, a naming quirk)."""

  @pydantic.field_validator('kinds')
  @classmethod
  def unique_kinds(cls, kinds: list[MarketKind] | None) -> list[MarketKind] | None:
    """Reject a kind listed twice."""
    if kinds is not None and len(set(kinds)) != len(kinds):
      raise ValueError('kinds must not repeat')
    return kinds

  def applies(self, kind: MarketKind | None) -> bool:
    """Whether a method of contract `kind` (`None`: any kind) applies to the venue."""
    return kind is None or self.kinds is None or kind in self.kinds

  def declares(self, method: str, kind: MarketKind | None) -> bool:
    """
    Whether this table declares `method`: it applies to the venue's kinds, and the
    support is `full` or a `partial` list naming it.

    Args:
      method: The method name.
      kind: The method's `kind` in its `docs/contract/<surface>.yml`.
    """
    return (
      self.support != 'none'
      and self.applies(kind)
      and (self.support == 'full' or method in (self.methods or ()))
    )


class VenueSupport(TypedDict):
  """One venue's `[support.<surface>]` table, as the docs site publishes it."""

  support: Literal['full', 'partial', 'none']
  auth: bool
  kinds: NotRequired[list[MarketKind]]
  """Market kinds the venue serves; absent means every kind. A method whose contract
  `kind` is not among them does not apply, even under `full` support (ADR 0056)."""
  methods: NotRequired[list[str]]
  """Which methods a `partial` surface implements; absent when it implements all of
  them, or when the package hasn't enumerated them."""
  note: NotRequired[str]


class SurfaceSupport(TypedDict):
  """One surface's row set in the support matrix."""

  supportedVenues: list[str]
  defaultVenues: list[str]
  venues: dict[str, VenueSupport]
  """Every venue declaring this surface, keyed by slug — `support = "none"` included,
  since a deliberate gap is still something the matrix has to say out loud."""


class ImplIds(pydantic.BaseModel):
  """The `[ids]` table: the venue-native ID forms the package emits, which the
  catalogue's translation keys for this platform must share."""

  model_config = pydantic.ConfigDict(extra='forbid')

  asset: Literal['symbol', 'index', 'address']
  """What an asset ID is: the venue's ticker symbol, a numeric token index, or a
  contract address (`native` for the chain's own coin)."""
  market: str | None = None
  """What a market ID looks like, in prose, e.g. `<base>/<quote>:<spot index>`."""
  note: str | None = None


AccountMode = Literal['public', 'address', 'token', 'private']
"""What a configured account can authenticate, weakest first: nothing, a public
address (or account index), a read-only token, or full private credentials."""

ACCOUNT_MODES: tuple[AccountMode, ...] = ('public', 'address', 'token', 'private')
"""Account modes in increasing order of authority."""


def mode_rank(mode: AccountMode) -> int:
  """Position of `mode` in `ACCOUNT_MODES`, for comparing modes."""
  return ACCOUNT_MODES.index(mode)


TESTNET_SUFFIXES = ('_testnet', '-testnet')
"""How a testnet venue id extends its mainnet slug: `_testnet`, or `-testnet` for a
hyphenated slug (`margin-trade-testnet`)."""


def mainnet_of(venue: str) -> str:
  """
  The mainnet slug a venue id belongs to: itself unless it is a testnet.

  Args:
    venue: An account's `venue` id, e.g. `hyperliquid_testnet`.
  """
  for suffix in TESTNET_SUFFIXES:
    if venue.endswith(suffix):
      return venue.removesuffix(suffix)
  return venue


def is_testnet(venue: str) -> bool:
  """Whether a venue id names a testnet."""
  return mainnet_of(venue) != venue


WaiverReason = Literal['credential_scope', 'account_setting']
"""Why a declared account read cannot be observed on the qualification account:
its credentials lack a permission scope the read needs (`AuthError`), or an account
setting puts the read outside the adapter's declared support (`NotImplementedError`)."""


class Waiver(pydantic.BaseModel):
  """One `[[qualification.market.waived]]` entry: a declared account read that may
  skip, visibly and without blocking release, on the qualification account."""

  model_config = pydantic.ConfigDict(extra='forbid')

  exchange: str
  """Exchange ID of the reference markets the waiver covers."""
  method: str
  """The account read waived."""
  reason: WaiverReason
  note: str = pydantic.Field(min_length=1)
  """Short explanation, kept with the declaration for reviewers and release notes."""


class MarketQualification(pydantic.BaseModel):
  """The `[qualification.market]` table: how release evidence reads account methods.

  Release qualification, not user-facing support: the support matrix ignores it.
  """

  model_config = pydantic.ConfigDict(extra='forbid')

  min_mode: Literal['address', 'token', 'private']
  """The weakest account mode release evidence may be recorded with."""
  address_methods: list[str] = []
  """Account reads served with only a public address or account index."""
  token_methods: list[str] = []
  """Account reads served with a read-only token; every other account read needs
  private credentials."""
  unsupported: dict[str, list[str]] = {}
  """Declared methods an exchange does not serve, keyed by exchange ID: the
  surface-level `methods` list cannot say that one product line lacks them."""
  waived: list[Waiver] = []
  """Declared reads the qualification account cannot observe (ADR 0042)."""


class ImplQualification(pydantic.BaseModel):
  """The optional `[qualification]` table of a package's `impl.toml`."""

  model_config = pydantic.ConfigDict(extra='forbid')

  market: MarketQualification | None = None


class ImplFile(pydantic.BaseModel):
  """The full shape of a package's `impl.toml` — a `support` table of tables plus the
  optional `ids` and `qualification` tables."""

  model_config = pydantic.ConfigDict(extra='forbid')

  support: dict[str, ImplSurfaceSupport] = {}
  ids: ImplIds | None = None
  qualification: ImplQualification = ImplQualification()


def load_impl_files(impl_dir: Path) -> dict[str, ImplFile]:
  """
  Parse and validate every `packages/impl/*/impl.toml` under `impl_dir`.

  Args:
    impl_dir: Path to the sdk repo's `packages/impl` directory.

  Returns:
    Validated `ImplFile`s keyed by package slug (its directory name), one per package
    that has an `impl.toml` at all.

  Raises:
    pydantic.ValidationError: some impl.toml doesn't match `ImplFile`'s shape.
  """
  files: dict[str, ImplFile] = {}
  for pkg_dir in sorted(impl_dir.iterdir()):
    impl_toml = pkg_dir / 'impl.toml'
    if not impl_toml.is_file():
      continue
    with open(impl_toml, 'rb') as f:
      raw = tomllib.load(f)
    files[pkg_dir.name] = ImplFile.model_validate(raw)
  return files


def load_method_kinds(contract: Path) -> dict[str, MarketKind | None]:
  """
  Read each method's `kind` from one `docs/contract/<surface>.yml`.

  Only `methods.<name>.kind` is read, so callers that never render examples (the
  qualification and evidence code) need not validate the whole contract.

  Args:
    contract: Path to the contract file.

  Returns:
    `{method: kind}`, `None` for a method that applies to every kind.
  """
  with open(contract) as f:
    raw = yaml.safe_load(f)
  kinds = pydantic.TypeAdapter(dict[str, MarketKind | None])
  return kinds.validate_python(
    {name: method.get('kind') for name, method in raw['methods'].items()}
  )


def kind_conflicts(
  impl_files: Mapping[str, ImplFile],
  surface: str,
  kinds: Mapping[str, MarketKind | None],
) -> list[str]:
  """
  Declarations of one surface that contradict its contract's method kinds.

  Args:
    impl_files: `load_impl_files()`'s output.
    surface: The contract's surface, e.g. `market`.
    kinds: `load_method_kinds()` of that surface's contract.

  Returns:
    One message per `partial` list naming a method outside the venue's `kinds`, and
    per `kinds` declared on a surface without kind-scoped methods.
  """
  scoped = any(kind is not None for kind in kinds.values())
  conflicts: list[str] = []
  for slug, data in impl_files.items():
    entry = data.support.get(surface)
    if entry is None or entry.kinds is None:
      continue
    if not scoped:
      conflicts.append(f'{slug}: {surface} has no kind-scoped methods to declare kinds')
    for method in entry.methods or ():
      if not entry.applies(kinds.get(method)):
        conflicts.append(
          f'{slug}: {surface}.{method} is {kinds.get(method)}-only, '
          f'outside kinds {entry.kinds}'
        )
  return conflicts


def method_universe(
  impl_files: Mapping[str, ImplFile],
  surface: str,
  method: str,
  *,
  kind: MarketKind | None,
) -> list[str]:
  """
  Every venue genuinely eligible to serve one method of one surface, per every
  `impl.toml`'s `[support.<surface>]` table.

  Args:
    impl_files: `load_impl_files()`'s output.
    surface: A surface name — by convention, a `docs/contract/<surface>.yml`'s own
      filename stem, never hardcoded by any caller.
    method: The method name (a `docs/contract/<surface>.yml`'s `methods.<method>` key).
    kind: The method's `kind` in that contract file (`None`: every kind).

  Returns:
    Slugs (impl_files' own iteration order — alphabetical) of every venue whose
    impl.toml declares the method (`ImplSurfaceSupport.declares`): the method applies
    to the venue's `kinds`, and the support is `full`, or `partial` with this method in
    its `methods` list. This is the outer bound on which venues a method's `.yml`
    template can be rendered for — see `sdk_dev.contract.render_method`.
  """
  return [
    slug
    for slug, data in impl_files.items()
    if (entry := data.support.get(surface)) is not None and entry.declares(method, kind)
  ]


def load_support_matrix(impl_dir: Path) -> dict[str, SurfaceSupport]:
  """
  Build `{surface: {supportedVenues: [...], defaultVenues: [...], venues: {...}}}` from
  every `packages/impl/*/impl.toml` under `impl_dir`.

  Args:
    impl_dir: Path to the sdk repo's `packages/impl` directory.

  Returns:
    One entry per surface named in any impl.toml's `[support.<surface>]` table. Venue
    order here is just directory-listing order (alphabetical) — display order is a
    presentation concern resolved downstream, by filtering registry.toml's own
    deliberately-ordered venue list against this data's membership, not by iterating
    this list directly.

  Raises:
    pydantic.ValidationError: some impl.toml doesn't match `ImplFile`'s shape.
  """
  matrix: dict[str, SurfaceSupport] = {}
  for slug, data in load_impl_files(impl_dir).items():
    for surface, entry in data.support.items():
      bucket = matrix.setdefault(
        surface, {'supportedVenues': [], 'defaultVenues': [], 'venues': {}}
      )
      venue: VenueSupport = {'support': entry.support, 'auth': entry.auth}
      if entry.kinds is not None:
        venue['kinds'] = entry.kinds
      if entry.methods:
        venue['methods'] = entry.methods
      if entry.note:
        venue['note'] = entry.note
      bucket['venues'][slug] = venue
      if entry.support == 'none':
        continue
      bucket['supportedVenues'].append(slug)
      if not entry.auth:
        bucket['defaultVenues'].append(slug)
  return matrix
