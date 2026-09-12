"""Runtime narrowing for data that is statically `object` or `Any`: a YAML document, an
exception payload. A bare `isinstance(x, dict)` narrows to `dict[Unknown, Unknown]`, which
the no-implicit-Any rules reject; these guards narrow to the read-only ABCs over `object`
instead, which is exactly what the runtime check establishes and nothing more.
"""

from typing_extensions import Mapping, Sequence, TypeGuard


def is_mapping(value: object) -> TypeGuard[Mapping[object, object]]:
  """Whether `value` is a mapping, of keys and values still to be checked."""
  return isinstance(value, Mapping)


def is_list(value: object) -> TypeGuard[Sequence[object]]:
  """Whether `value` is a list, of items still to be checked."""
  return isinstance(value, list)
