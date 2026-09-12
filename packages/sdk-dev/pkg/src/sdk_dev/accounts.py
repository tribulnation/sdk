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

# Deribit selects these defaults in properties rather than dataclass fields.
# Keep the mainnet names explicit in the displayed credential configuration.
CREDENTIAL_OVERRIDES = {
  'deribit': {
    'client_id': '$DERIBIT_CLIENT_ID',
    'client_secret': '$DERIBIT_CLIENT_SECRET',
  },
}


def generate_accounts_toml(*, public: bool = False) -> dict[str, str]:
  """
  Build a `{venue_slug: toml_block}` map, one `[accounts.<slug>]` block per venue, from
  the real `tribulnation.sdk.impl.accounts` dataclasses.

  Args:
    public: Emit explicit public accounts without credential placeholders. This
      expresses account configuration capability, not per-method public support.

  Returns:
    Raw TOML text per venue slug, e.g. `mexc: '[accounts.mexc]\\nvenue = "mexc"\\n...'`.
  """
  from tribulnation.sdk.impl.accounts import (
    BaseAccount,
    Binance,
    Bit2Me,
    Bitget,
    Bybit,
    Coinbase,
    Deribit,
    Dydx,
    Evm,
    Hyperliquid,
    Kraken,
    Kucoin,
    Mexc,
  )

  classes: dict[str, type[BaseAccount]] = {
    'dydx': Dydx,
    'hyperliquid': Hyperliquid,
    'mexc': Mexc,
    'binance': Binance,
    'bitget': Bitget,
    'bit2me': Bit2Me,
    'kraken': Kraken,
    'ethereum': Evm,
    'bybit': Bybit,
    'coinbase': Coinbase,
    'kucoin': Kucoin,
    'deribit': Deribit,
  }

  blocks: dict[str, str] = {}
  for slug, cls in classes.items():
    if public and not any(f.name == 'public' for f in dataclasses.fields(cls)):
      continue
    lines = [f'[accounts.{slug}]']
    for f in dataclasses.fields(cls):
      if f.name == 'venue':
        value = VENUE_OVERRIDES.get(slug, f.default)
      elif public:
        continue
      elif f.name in CREDENTIAL_OVERRIDES.get(slug, {}):
        value = CREDENTIAL_OVERRIDES[slug][f.name]
      elif isinstance(f.default, str) and f.default.startswith('$'):
        value = f.default
      else:
        continue
      lines.append(f'{f.name} = "{value}"')
    if public:
      lines.append('public = true')
    blocks[slug] = '\n'.join(lines)
  return blocks
