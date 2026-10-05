# ADR 0032: SDK-owned gateway and lazy tn command

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: proposed; implemented in this PR, not release-verified
2. Date: 2026-10-05

## Context

The engine carries a gateway server, wire codec and SDK proxy that follow SDK
market types. Maintaining them in a separate release allows the transport and
interface to drift. The public `tribulnation-cli` launcher now supports independent
packages through lazy `tribulnation.commands` entry points.

## Decision

Move the existing gateway into `tribulnation.sdk.gateway` in the SDK distribution,
with transport/runtime dependencies under the `gateway` extra. Register
`gateway = tribulnation.sdk.gateway.cli:app`; the launcher is a core dependency
because entry-point registration cannot depend on installed extras. Import only
the CLI for command help and defer transport, configuration and SDK startup until
execution. A missing gateway extra produces an installation hint.

Keep the WebSocket protocol and supported operations. Public classes are
`ProxySDK`, `Gateway` and `GatewayError`. `run_gateway(socket_path, sdk)` and
`gateway_app(sdk)` own an injected `TradingMarkets` instance instead of importing
`EngineConfig`. The CLI defaults to `sdk.toml`; explicit engine TOML files remain
supported through their accounts and legacy daemon socket. Keep existing flags,
logging, diagnostics, socket default and Unix process behavior.

Transport venue settings as nested objects without importing optional venue
implementations or rewriting their forward references in the global SDK module.
Preserve settings keys and values for the server's adapter. This changes the old
codec's validation location and avoids dropping unrecognized settings; it does
not change valid existing settings on the wire.

The [gateway guide](../../docs/gateway.md) defines the supported scope. Engine
process IPC, required handles, worker placement and orchestration remain in the
engine. Speculative engine gateway proposals are not accepted SDK requirements.

## Alternatives considered

1. A separate gateway distribution would create another SDK compatibility and
   version boundary for code that follows SDK types.
2. Leaving the implementation in the engine preserves the drift risk.
3. Eagerly importing all venue implementations would make a remote client install
   local drivers and expensive dependencies it does not need.
4. Redesigning the protocol, stream fan-out or order ID generation during the port
   would make this ownership change harder to review and qualify.

## Consequences

The SDK releases the interface, codec and proxy together. Optional gateway
installation remains separate from venue selection. Engine consumers must change
imports and pass SDK inputs; compatibility aliases are engine work.

Regression coverage includes the inherited Unix-socket tests, settings wire
fixtures, account/configuration loading, lazy imports and owned SDK resource
lifetime. Gateway-only installation is checked without engine or venue packages.
This does not qualify live venue trading, fill delivery or general SDK parity.

SDK releases still require the repository's fingerprinted read-suite and
consistency evidence for every supported implementation. No evidence is forged,
updated by hand or waived for this port; missing/stale qualification keeps the
release PR unready to merge.
