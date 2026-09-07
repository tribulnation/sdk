"""Static walk of a typed client's namespace tree: every endpoint method reachable from
the root, with its dotted path (`classic.mix.market.symbol_price`), signature and
one-line summary.

This is the discovery step of a PoC. The mapping is picked from what the client actually
exposes, listed here, instead of from memory of it. Griffe reads the source without
importing it, so annotations come back as written (`MixProductType`, not the pydantic
`Annotated[...]` it expands to at runtime), and a module-level `Response = list[...]`
alias is expanded in place so the row says what the call returns.

Typed clients compose namespaces as `cached_property`s returning the next endpoint class
down, with leaf methods contributed by mixins; both are walked. Members coming from the
client's own `core` package or from `typed_core` are transport plumbing (`request`,
`__aenter__`), not endpoints, and are left out.
"""

from pathlib import Path
from typing_extensions import Iterable, NamedTuple
import logging
import re

import griffe

logging.getLogger('griffe').setLevel(logging.ERROR)

MAX_DEPTH = 8
"""Namespace nesting bound, so a property returning its own class can't recurse forever."""
PLUMBING = ('typed_core',)
"""Packages whose members are never endpoints, whatever client they show up in."""


class Parameter(NamedTuple):
  """One parameter of a method, as written in the source."""

  name: str
  kind: str
  """Griffe's kind label: `positional-only`, `positional or keyword`, `keyword-only`,
  `variadic positional` or `variadic keyword`."""
  annotation: str | None
  default: str | None


class Method(NamedTuple):
  """One endpoint method reachable from the client root."""

  path: str
  """Dotted path from the root, e.g. `classic.mix.market.symbol_price`."""
  parameters: list[Parameter]
  returns: str | None
  summary: str
  """First line of the docstring, empty when there is none."""


class ClientLookupError(Exception):
  """The typed client package or its root class couldn't be found."""


def load_client(
  module: str,
  class_name: str | None = None,
  *,
  search_paths: list[Path] | None = None,
) -> tuple[griffe.Module, griffe.Class]:
  """
  Load a typed client package statically and find its root class.

  Args:
    module: The package, e.g. `typed_bitget`.
    class_name: The root class. Defaults to the one class defined in `<module>.main`,
      which is where every generated client keeps it.
    search_paths: Where to look for the package, on top of `sys.path`.

  Raises:
    ClientLookupError: the package can't be loaded, or the root class can't be found.
  """
  try:
    package = griffe.load(
      module,
      docstring_parser='google',
      resolve_aliases=True,
      resolve_implicit=True,
      search_paths=search_paths,
    )
  except Exception as e:
    raise ClientLookupError(f'cannot load {module!r}: {e}') from e
  assert isinstance(package, griffe.Module)
  if class_name is not None:
    found = find_class(package, class_name)
    if found is None:
      raise ClientLookupError(f'{module!r} defines no class {class_name!r}')
    return package, found
  main = package.members.get('main')
  candidates = (
    [c for c in main.classes.values() if not c.is_alias]
    if isinstance(main, griffe.Module)
    else []
  )
  if len(candidates) != 1:
    raise ClientLookupError(
      f'{module!r} has no single root class in {module}.main; name one explicitly'
    )
  return package, candidates[0]


def find_class(module: griffe.Module, name: str) -> griffe.Class | None:
  """
  Find a class by name anywhere in a package, breadth-first.

  Args:
    module: The package to search.
    name: The class name.
  """
  queue = [module]
  while queue:
    current = queue.pop(0)
    found = current.classes.get(name)
    if found is not None and not found.is_alias:
      return found
    queue += current.modules.values()
  return None


def methods(cls: griffe.Class, package: str) -> list[Method]:
  """
  Every endpoint method reachable from `cls`, in namespace order.

  Args:
    cls: The client root class.
    package: The client package name, whose `core` subpackage is skipped as plumbing.
  """
  return list(walk(cls, package, prefix='', depth=0))


def walk(
  cls: griffe.Class, package: str, *, prefix: str, depth: int
) -> Iterable[Method]:
  """
  Yield the methods of `cls` and, through its property namespaces, of every class below.

  Args:
    cls: The class to walk.
    package: The client package name.
    prefix: Dotted path of `cls` from the root, with a trailing dot unless empty.
    depth: How many namespaces deep `cls` is.
  """
  for name, member in cls.all_members.items():
    if name.startswith('_'):
      continue
    try:
      target = member.final_target if isinstance(member, griffe.Alias) else member
    except Exception:
      continue
    if plumbing(target, package):
      continue
    if isinstance(target, griffe.Attribute):
      child = namespace(target)
      if child is not None and depth < MAX_DEPTH:
        yield from walk(child, package, prefix=f'{prefix}{name}.', depth=depth + 1)
    elif isinstance(target, griffe.Function):
      if target.labels & {'classmethod', 'staticmethod', 'property'}:
        continue
      yield Method(
        path=f'{prefix}{name}',
        parameters=parameters(target),
        returns=returns(target),
        summary=summary(target),
      )


def plumbing(obj: griffe.Object, package: str) -> bool:
  """
  Whether `obj` is defined by transport code rather than by an endpoint.

  Args:
    obj: A resolved class member.
    package: The client package name.
  """
  path = obj.parent.path if obj.parent is not None else obj.path
  return path.startswith(f'{package}.core') or path.startswith(PLUMBING)


def namespace(attr: griffe.Attribute) -> griffe.Class | None:
  """
  The class a property namespace returns, when its annotation names one.

  Args:
    attr: A class member griffe read as a property.
  """
  if 'property' not in attr.labels or attr.annotation is None:
    return None
  try:
    path = attr.module.resolve(str(attr.annotation))
    target = attr.modules_collection[path]
    if isinstance(target, griffe.Alias):
      target = target.final_target
  except Exception:
    return None
  return target if isinstance(target, griffe.Class) else None


def parameters(
  fn: griffe.Function, *, skip: Iterable[str] = ('self', 'validate')
) -> list[Parameter]:
  """
  A function's parameters, minus the receiver and the per-call `validate` override.

  Args:
    fn: The function.
    skip: Parameter names to leave out.
  """
  return [
    Parameter(
      name=p.name,
      kind=p.kind.value if p.kind is not None else 'positional or keyword',
      annotation=str(p.annotation) if p.annotation is not None else None,
      default=str(p.default) if p.default is not None else None,
    )
    for p in fn.parameters
    if p.name not in skip
  ]


def returns(fn: griffe.Function) -> str | None:
  """
  A function's return annotation, with a module-level alias like `Response` expanded.

  Args:
    fn: The function.
  """
  if fn.returns is None:
    return None
  text = str(fn.returns)
  alias = fn.module.members.get(text)
  if isinstance(alias, griffe.Attribute) and alias.value is not None:
    return str(alias.value)
  return text


def summary(fn: griffe.Function) -> str:
  """
  First line of a function's docstring.

  Args:
    fn: The function.
  """
  return fn.docstring.value.splitlines()[0].strip() if fn.docstring else ''


def signature(parameters: Iterable[Parameter], returns: str | None = None) -> str:
  """
  Render parameters back into `(a, /, b, *, c: int = 1) -> R` form.

  Args:
    parameters: The parameters, in declaration order.
    returns: The return annotation, if any.
  """
  parts: list[str] = []
  positional_only = False
  keyword_only = False
  for p in parameters:
    if p.kind == 'positional-only':
      positional_only = True
    elif positional_only:
      parts.append('/')
      positional_only = False
    if p.kind == 'keyword-only' and not keyword_only:
      parts.append('*')
      keyword_only = True
    if p.kind == 'variadic positional':
      keyword_only = True
    prefix = {'variadic positional': '*', 'variadic keyword': '**'}.get(p.kind, '')
    text = f'{prefix}{p.name}'
    if p.annotation is not None:
      text += f': {p.annotation}'
    if p.default is not None:
      text += f' = {p.default}'
    parts.append(text)
  if positional_only:
    parts.append('/')
  rendered = f'({", ".join(parts)})'
  return f'{rendered} -> {returns}' if returns is not None else rendered


def render(
  found: Iterable[Method],
  *,
  paths: Iterable[str] = (),
  grep: str | None = None,
) -> str:
  """
  Render methods as `path(signature)` lines, each followed by its indented summary.

  Args:
    found: The methods, from `methods()`.
    paths: Keep methods under these dotted namespace prefixes only.
    grep: Keep methods whose path or summary matches this regex, case-insensitively.
  """
  prefixes = tuple(paths)
  pattern = re.compile(grep, re.IGNORECASE) if grep else None
  lines: list[str] = []
  for m in found:
    if prefixes and not any(
      m.path == p or m.path.startswith(f'{p}.') for p in prefixes
    ):
      continue
    if pattern and not (pattern.search(m.path) or pattern.search(m.summary)):
      continue
    lines.append(f'{m.path}{signature(m.parameters, m.returns)}')
    if m.summary:
      lines.append(f'  {m.summary}')
  return '\n'.join(lines)


def surface(
  module: str,
  class_name: str | None = None,
  *,
  paths: Iterable[str] = (),
  grep: str | None = None,
) -> str:
  """
  Render a typed client's endpoint surface in one call, for a notebook cell.

  Args:
    module: The client package, e.g. `typed_bitget`.
    class_name: The root class; defaults to the one defined in `<module>.main`.
    paths: Keep methods under these dotted namespace prefixes only.
    grep: Keep methods whose path or summary matches this regex, case-insensitively.
  """
  _, cls = load_client(module, class_name)
  return render(methods(cls, module), paths=paths, grep=grep)
