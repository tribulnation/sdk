"""Local stub for `lazy_loader`, which carries no annotations of its own.

`attach` and `attach_stub` are unannotated, and `attach` returns three closures defined in
its own body, so pyright infers a partially-unknown tuple however hard it looks --
`useLibraryCodeForTypes` is already on by default and does not help. Every `__init__.py`
unpacking that call then reports `__getattr__` and `__all__` as partially unknown under the
repo's strict settings.

Only the two members this repo uses are declared. Pyright finds this without configuration:
`stubPath` defaults to `./typings`.
"""

from typing_extensions import Any, Callable, Iterable, Mapping

def attach(
  package_name: str,
  submodules: Iterable[str] | None = None,
  submod_attrs: Mapping[str, list[str]] | None = None,
) -> tuple[Callable[[str], Any], Callable[[], list[str]], list[str]]:
  """Attach lazily loaded submodules, functions, or other attributes."""
  ...

def attach_stub(
  package_name: str, filename: str
) -> tuple[Callable[[str], Any], Callable[[], list[str]], list[str]]:
  """Attach lazily loaded submodules, functions and attributes, from a `.pyi` stub."""
  ...
