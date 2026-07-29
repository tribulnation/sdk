# AGENTS.md

## Overview

- `sdk`: abstract SDK interface
- `impl`: exchange-specific implementations

## Actions

1. Bump and publish SDK: `cd sdk/ && just republish`
2. Bump and publish implementation, e.g. `bitget`: `cd impl/bitget/ && just republish`

`republish` bumps the **patch** version (`bump.sh` is patch-only). For a minor or
major, edit `version` in the package's `pyproject.toml` first and then run
`just build publish` — `republish` would bump again on top of it.

Publish the SDK before the impls: their `tribulnation-sdk` floors require the new
version to exist on PyPI. Raise those floors in the same release as any change to
a base class impls subclass — an impl resolved against an older SDK fails
silently rather than at import.

### Python Guidelines

@.agents/rules/python.md
