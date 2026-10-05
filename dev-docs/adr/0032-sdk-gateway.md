# ADR 0032: SDK-owned gateway and lazy tn command

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: proposed; implemented in this PR, not release-verified
2. Date: 2026-10-05

Amended by [ADR 0033](0033-change-scoped-release-evidence.md): release evidence is
required only for venues affected since the previous package release.

## Context

A gateway server, wire codec and remote SDK proxy closely follow SDK market types.
Releasing these together avoids interface drift. The public `tribulnation-cli`
launcher supports independent packages through lazy `tribulnation.commands` entry
points.

## Decision

Provide `tribulnation.sdk.gateway` in the SDK distribution, with transport/runtime
dependencies under the `gateway` extra. Register
`gateway = tribulnation.sdk.gateway.cli:app`; the launcher is a core dependency
because entry-point registration cannot depend on installed extras. Import only
the CLI for command help and defer transport, configuration and SDK startup until
execution. A missing gateway extra produces an installation hint.

Public classes are `ProxySDK`, `Gateway` and `GatewayError`.
`run_gateway(socket_path, sdk)` and `gateway_app(sdk)` own an injected
`TradingMarkets` instance. The CLI defaults to `sdk.toml`, with SDK
`[accounts.<id>]` tables and `[gateway].socket`. `--socket/-s` overrides the file;
the default `/tmp/tribulnation-sdk.sock` is shared with `ProxySDK.at()`.
`--config/-c` selects another SDK config file and `--verbose/-v` controls logging.
No other application's configuration schema or socket defaults are supported.

Transport venue settings as nested objects without importing optional venue
implementations or rewriting their forward references in the global SDK module.
Preserve settings keys and values for the server's adapter to validate. The
[gateway guide](../../docs/gateway.md) defines the supported operations and limits.
Application orchestration and process-to-process IPC are outside this contract.

## Alternatives considered

1. A separate gateway distribution creates another SDK compatibility and version
   boundary for code that follows SDK types.
2. Eagerly importing all venue implementations makes a remote client install local
   drivers and expensive dependencies it does not need.
3. Supporting application-specific configuration couples the SDK to its consumers;
   consumers should translate their own configuration into SDK inputs instead.
4. Redesigning the protocol, stream fan-out or order ID generation in this release
   would make the gateway addition harder to review and qualify.

## Consequences

The SDK releases the interface, codec and proxy together. Optional gateway
installation remains separate from venue selection. Applications configure the
SDK API or its standalone command explicitly.

Regression coverage includes Unix-socket tests, settings wire fixtures, SDK
account/configuration loading, lazy imports and owned SDK resource lifetime.
Gateway-only installation is checked without venue packages. This does not
qualify live venue trading, fill delivery or general SDK parity.

Under [ADR 0034](0034-offline-evidence-maintenance.md), this gateway and verifier
migration requires offline regression checks without new venue runs. Relevant
adapter, shared SDK and live-check behavior changes still require fingerprinted
read-suite/consistency evidence. Existing reports remain untouched.
