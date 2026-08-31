"""JSON Schema generation for `sdk.toml`, from the real `Account` union.

Generated straight off `tribulnation.sdk.impl.accounts.Account` via pydantic's
`TypeAdapter` — never hand-duplicated, so it can't drift from the real dataclasses the way
a hand-typed schema could.
"""

import pydantic

SCHEMA_TITLE = 'sdk.toml'
SCHEMA_DESCRIPTION = (
  "Account configuration consumed by tribulnation-sdk's <Surface>SDK.load('sdk.toml') "
  '(MarketSDK, EarnSDK, WalletSDK, ReportSDK).'
)


def generate_schema() -> dict:
  """
  Build the full JSON Schema document for `sdk.toml`'s `[accounts.<id>]` tables.

  `$defs` is hoisted to the document root: pydantic nests it under the `accounts`
  property's own schema, but a `$ref` like `#/$defs/Binance` is a JSON Pointer resolved
  from the *document* root regardless of where it appears, so leaving `$defs` nested there
  would silently break every reference. `additionalProperties: false` is set on each
  variant (pydantic leaves it unset for plain dataclasses) so an editor validating against
  this schema — a mistyped field, or a field from the wrong venue — is flagged, not silently
  accepted.

  Returns:
    A JSON-serializable dict, valid against the 2020-12 JSON Schema meta-schema.
  """
  from tribulnation.sdk.impl.accounts import Account

  adapter = pydantic.TypeAdapter(dict[str, Account])
  accounts_schema = adapter.json_schema()
  defs = accounts_schema.pop('$defs', {})
  for definition in defs.values():
    definition.setdefault('additionalProperties', False)

  return {
    '$schema': 'https://json-schema.org/draft/2020-12/schema',
    'title': SCHEMA_TITLE,
    'description': SCHEMA_DESCRIPTION,
    'type': 'object',
    'properties': {'accounts': accounts_schema},
    '$defs': defs,
  }
