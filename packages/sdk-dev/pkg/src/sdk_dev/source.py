"""Signatures and docstrings for `docs/contract/*.yml` methods, read from the real
source with Griffe — the yml only names a method, the code documents it. Static analysis
(no import), so annotations come back exactly as written in the source file.
"""

import logging

import griffe
from typing_extensions import TypedDict

logging.getLogger('griffe').setLevel(logging.ERROR)


class SourceMethod(TypedDict):
  """What the docs show for one method, all read from its definition."""

  signature: str
  """`name(params) -> Return`, parameter names and defaults only, `self` dropped."""
  description: str
  """The docstring's first paragraph, joined onto one line."""
  semantics: str
  """Everything after the first paragraph, as markdown — Google sections become lists."""


class SourceLookupError(Exception):
  """A `ref`/method pair in a contract file doesn't exist in the source."""


class Source:
  """Griffe-backed lookup of SDK methods by `module:Class` ref and method name."""

  def __init__(self):
    self.modules: dict[str, griffe.Module] = {}

  def method(self, ref: str, name: str) -> SourceMethod:
    """
    Resolve one method.

    Args:
      ref: `module.path:ClassName`, e.g. `tribulnation.sdk.market.markets:TradingMarkets`.
        Inherited members resolve too, so a `ref` can name the public facade class.
      name: The method's name on that class.

    Raises:
      SourceLookupError: the module, class or method doesn't exist.
    """
    module_path, _, class_name = ref.partition(':')
    if not class_name:
      raise SourceLookupError(f'{ref!r}: expected `module.path:ClassName`')
    if module_path not in self.modules:
      try:
        loaded = griffe.load(module_path, docstring_parser='google')
      except Exception as e:
        raise SourceLookupError(
          f'{ref!r}: cannot load module {module_path!r}: {e}'
        ) from e
      assert isinstance(loaded, griffe.Module)
      self.modules[module_path] = loaded
    module = self.modules[module_path]
    try:
      cls = module[class_name]
    except KeyError:
      raise SourceLookupError(f'{ref!r}: no class {class_name!r} in {module_path!r}')
    member = cls.all_members.get(name)
    if member is None or not member.is_function:
      raise SourceLookupError(f'{ref}.{name}: no such method')
    fn = member.final_target if isinstance(member, griffe.Alias) else member
    assert isinstance(fn, griffe.Function)
    description, semantics = split_docstring(fn)
    return {
      'signature': format_signature(fn, name),
      'description': description,
      'semantics': semantics,
    }


def format_signature(fn: griffe.Function, name: str) -> str:
  """
  `name(params) -> Return` with parameter names and defaults only, no annotations.

  `self`/`cls` are dropped; `/` and `*` markers are kept so positional-only and
  keyword-only parameters read as they must be called. An `@asynccontextmanager`
  function's `AsyncGenerator[X]` annotation is shown as `AsyncContextManager[X]`, which is
  what the caller actually receives.
  """
  params = [p for p in fn.parameters if p.name not in ('self', 'cls')]
  kinds = griffe.ParameterKind
  has_var_positional = any(p.kind is kinds.var_positional for p in params)
  parts: list[str] = []
  star_emitted = has_var_positional
  for i, p in enumerate(params):
    if p.kind is kinds.keyword_only and not star_emitted:
      parts.append('*')
      star_emitted = True
    text = p.name
    if p.kind is kinds.var_positional:
      text = f'*{text}'
    elif p.kind is kinds.var_keyword:
      text = f'**{text}'
    if p.default is not None:
      text = f'{text}={p.default}'
    parts.append(text)
    last_positional_only = p.kind is kinds.positional_only and (
      i + 1 == len(params) or params[i + 1].kind is not kinds.positional_only
    )
    if last_positional_only:
      parts.append('/')
  returns = str(fn.returns) if fn.returns is not None else ''
  decorators = {str(d.value) for d in fn.decorators}
  if 'asynccontextmanager' in decorators and returns.startswith('AsyncGenerator['):
    inner = returns[len('AsyncGenerator[') : -1]
    returns = f'AsyncContextManager[{inner.split(", None")[0]}]'
  signature = f'{name}({", ".join(parts)})'
  return f'{signature} -> {returns}' if returns else signature


def split_docstring(fn: griffe.Function) -> tuple[str, str]:
  """
  Split a Google-style docstring into (description, semantics).

  The description is the first paragraph, whitespace-collapsed. The semantics is every
  remaining section rendered as markdown: free text verbatim, `Args:`/`Returns:`/`Raises:`
  as bullet lists, `Examples:` as a code block.
  """
  if fn.docstring is None:
    return '', ''
  kinds = griffe.DocstringSectionKind
  description: str | None = None
  chunks: list[str] = []
  for section in fn.docstring.parsed:
    if section.kind is kinds.text:
      text = section.value.strip()
      if description is None:
        first, _, rest = text.partition('\n\n')
        description = ' '.join(first.split())
        if rest.strip():
          chunks.append(rest.strip())
      else:
        chunks.append(text)
    elif section.kind is kinds.parameters:
      items = [f'- `{p.name}`: {p.description}' for p in section.value]
      chunks.append('**Args**\n\n' + '\n'.join(items))
    elif section.kind is kinds.returns:
      items = [r.description for r in section.value]
      chunks.append('**Returns** ' + ' '.join(items))
    elif section.kind is kinds.raises:
      items = [f'- `{r.annotation}`: {r.description}' for r in section.value]
      chunks.append('**Raises**\n\n' + '\n'.join(items))
    elif section.kind is kinds.examples:
      for _, example in section.value:
        chunks.append(f'```python\n{example}\n```')
  return description or '', '\n\n'.join(chunks)
