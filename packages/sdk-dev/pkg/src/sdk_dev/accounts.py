"""TOML `[accounts.<id>]` block generation for `sdk.toml`, from the real `Account`
dataclasses — same idea as `sdk_dev.schema`, but reading `dataclasses.fields()` directly
instead of going through a JSON Schema: every field whose *default* is a `$ENV_VAR`
placeholder string is a credential the reader has to fill in; everything else
(`public`, `validate`, `uta`, `parent_subaccount`, ...) is a non-credential default not
worth showing. Never hand-duplicated, so it can't drift from the real dataclasses.
"""

import dataclasses

# Evm's `venue` field has no default — there are several real EVM chains
# (`Literal['ethereum', 'arbitrum', ...]`), so which one to show can't be introspected.
# This repo's docs only ever demonstrate the 'ethereum' chain; the only manual choice
# this module needs to make.
VENUE_OVERRIDES = {'ethereum': 'ethereum'}


def generate_accounts_toml() -> dict[str, str]:
  """
  Build a `{venue_slug: toml_block}` map, one `[accounts.<slug>]` block per venue, from
  the real `tribulnation.sdk.impl.accounts` dataclasses.

  Returns:
    Raw TOML text per venue slug, e.g. `mexc: '[accounts.mexc]\\nvenue = "mexc"\\n...'`.
  """
  from tribulnation.sdk.impl.accounts import (
    Binance,
    Bit2Me,
    Bitget,
    Dydx,
    Evm,
    Hyperliquid,
    Mexc,
  )

  classes = {
    'dydx': Dydx,
    'hyperliquid': Hyperliquid,
    'mexc': Mexc,
    'binance': Binance,
    'bitget': Bitget,
    'bit2me': Bit2Me,
    'ethereum': Evm,
  }

  blocks: dict[str, str] = {}
  for slug, cls in classes.items():
    lines = [f'[accounts.{slug}]']
    for f in dataclasses.fields(cls):
      if f.name == 'venue':
        value = VENUE_OVERRIDES.get(slug, f.default)
      elif isinstance(f.default, str) and f.default.startswith('$'):
        value = f.default
      else:
        continue
      lines.append(f'{f.name} = "{value}"')
    blocks[slug] = '\n'.join(lines)
  return blocks
