# tribulnation-lighter 0.11.0

Requires SDK >=2.17.0 and typed-lighter >=0.3.0. The endpoints can be overridden.

New:

1. Endpoint overrides for other servers (for example local fake exchanges in stress
   tests): `rest_url` and `ws_url`; the chain id still follows the venue (mainnet or
   testnet). `LighterMarket.new` takes the same keywords, and the SDK
   `[accounts.<id>]` config accepts them (sdk#240). Unset, the endpoints are
   unchanged.

Every other method is unchanged.

The typed-lighter floor rises to 0.3.0, which adds the endpoint overrides. The SDK
floor is unchanged; SDK 2.18.0 requires this version so that its account config can
pass the new keywords.
