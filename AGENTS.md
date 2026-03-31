# AGENTS.md

## Overview

- `sdk`: abstract SDK interface
- `impl`: exchange-specific implementations

## Guidelines

### Coding Style

1. Never use `from __future__ import annotations`
2. Use double quotes for docstrings and single quotes for normal strings, e.g.:
   ```python
   def function(lit: Literal['a', 'b'] = 'a'):
      """This is a docstring"""
      return f'{lit}\n'
3. Never add `__all__ = [...]` to `__init__.py` files.