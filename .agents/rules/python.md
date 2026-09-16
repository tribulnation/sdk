<!-- vendored from workspace/.agents/rules/python.md — do not edit; run `python scripts/sync.py agents` -->
# Python Guidelines

## Notes

- Most workspaces have a local `.venv` directory. To run python, use `.venv/bin/python`

## Style Guide

Formatting and the mechanical rules (indentation, quotes, `typing_extensions`, no `from __future__ import annotations`, built-in generics, `X | None`) are enforced by the shared ruff config; see Tooling. This document only covers what a linter cannot check.

### General Notes

- Don't add `__all__ = [...]` to `__init__.py` files, it's innecessary. They're only used in `__init__.pyi` files for use with the `lazy-loader` package.
- Don't create `__init__.pyi` files unless to use with `lazy-loader`. That can be used when it'd make sense to import only one of the submodules as standalone, and the rest are heavy to import.
- Don't `from ... import symbol as symbol` in `__init__.py`. Don't use `as` unless explicitly requested by the user.
- Add a small docstring to every function, class, and module. Make it concise and descriptive. If you're not sure what to write, consider whether the function is necesary or can be removed.
- Don't assert/cast types with a discriminator field. Example:

  ```python
  class Type1:
    type: Literal['type1']

  class Type2:
    type: Literal['type2']

  x: Type1 | Type2 = ...
  if x.type == 'type1':
    # here x is Type1, no need to do either of these
    x = cast(Type1, x) # WRONG
    assert isinstance(x, Type1) # WRONG
  ```

### Docstrings

- Use a Google-compatible section style. Structured sections should stay parseable by Griffe/mkdocstrings.
- Use `Args:`, `Returns:`, `Raises:`, `Examples:`, and `References:` when useful.
- For `Args:`, write each parameter as `name: Description.`
- Do not repeat type annotations or default values in docstring prose unless the
  runtime behavior differs from the signature. The Python annotation and default
  value remain the source of truth.
- Put upstream documentation links under `References:`.

Example:

```python
def http(
  cls, wallet: Wallet | None = None, /, *,
  mainnet: bool = True, validate: bool = True, public: bool = False,
):
  """
  Create a new Hyperliquid client with HTTP transport.

  Args:
    wallet: Private key or account object.
    mainnet: Use mainnet when true, testnet when false.
    validate: Validate responses.
    public: Allow public-only usage without a wallet.

  References:
    - [Hyperliquid API docs](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api)
  """
```

### Typing

- Use precise type annotations as much as possible. Especially, if a `TypedDict` exists, use it instead of `dict`. Also if a `Literal` is appropriate, use it instead of a string.
- Use `Literal` instead of enums.
- Use `TypedDict` for wire shapes: anything a client sends or receives as JSON. Use frozen `dataclasses` for domain models that code passes around and reasons about; `pydantic.TypeAdapter` over the dataclass is the JSON boundary, so there is one schema.
- Document non-trivial fields using docstrings below each field. Don’t leave any extra empty lines. E.g:

  ```python
  class LimitOrder(TypedDict):
	price: Decimal
	"""Order price"""
	amount: Decimal
	"""Amount to buy (or negative if sell)"""
  ```	

- For `typing_extensions.TypedDict`s, use either of these depending on the fields.
    1. If most are not required, use `total=False` + `Required`:
        
        ```python
        from typing_extensions import TypedDict, Required
        
        class Order(TypedDict, total=False):
        	asset: Required[str]
        	price: str
        	amount: str
        ```
        
    2. Otherwise, use `NotRequired`
        
        ```python
        from typing_extensions import TypedDict, NotRequired
        
        class Order(TypedDict):
        	asset: str
        	price: str
        	amount: NotRequired[str]
        ```

- If those are parameters in a function, a similar thing can be achieved using `overload`. Use common sense: if a union type makes sense, do that. Otherwise, you can do e.g.:
    
    ```python
    from typing_extensions import overload, Literal
    
    @overload
    async def buy(order_type: Literal['limit'], price: str):
    	...
    @overload
    async def buy(order_type: Literal['market']):
    	...
    async def buy(order_type: str, price: str | None = None):
    	...
    ```

- Use unions to ensure precision. No invalid parameter combination should type-check. For example, if the docs state:
    
    ```
    - order_type: 'limit' | 'market'
    - price: number, only for limit orders
    ```
    
    Then you must NOT type it like this
    
    ```python
    from typing_extensions import TypedDict, Literal, NotRequired
    
    class Order(TypedDict):
    	order_type: Literal['limit', 'market']
    	price: NotRequired[str]
    ```
    
    But instead the more accurate:
    
    ```python
    from typing_extensions import TypedDict, Literal, NotRequired
    
    class LimitOrder(TypedDict):
    	order_type: Limit['limit']
    	price: NotRequired[str]
    	
    class MarketOrder(TypedDict):
    	order_type: Limit['market']
    	
    Order = LimitOrder | MarketOrder
    ```

### Functions

- When having multiple parameters with the same type, force them to be kwargs. So, avoid this:
    
    ```python
    async def buy(price: str, amount: str):
    	...
    ```
    
    in favor of:
    
    ```python
    async def buy(*, price: str, amount: str):
    	...
    ```

- When the return type is `None`, don't annotate it (it's already implicit).
- Prefer single-line headers when not too long; the formatter decides the layout of multi-line ones.
- Avoid names starting with underscore unless they are really private, concrete and not reusable.

### Tooling

Formatting is `ruff format`'s job, not this document's. Where the two disagree,
the formatter wins — it is what CI gates on, and a rule it overwrites on the next
run is a rule nobody can follow.

The shared config is vendored at `.agents/tools/python/ruff.toml`. Use it rather
than a local copy:

```sh
ruff check --config .agents/tools/python/ruff.toml <paths>
ruff format --config .agents/tools/python/ruff.toml <paths>
```

A repo needing a rule the shared config lacks should add it to the canonical
`workspace/.agents/tools/python/ruff.toml` and re-sync, so every repo gets it.
A divergent local `ruff.toml` is drift.
