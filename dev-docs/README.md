# SDK developer documentation

For contributors and release maintainers. Start with [CONTRIBUTING.md](../CONTRIBUTING.md)
for repository setup, development commands and implementation guidance.

1. [Local consistency checks and release evidence](local-checks.md): live test
   configuration, recorded observations, fingerprints and offline release gates.
2. [Architecture Decision Records](adr/README.md): accepted decisions, rationale,
   superseded contracts and the template for new decisions.
3. [Release workflow](../CONTRIBUTING.md#releasing) and
   [recorded evidence](../release-evidence/README.md).

## Documentation boundaries

1. [User documentation](../docs/index.md) explains installation, configuration,
   public API contracts, examples and supported capabilities. Readers should not
   need an ADR or SDK-dev instructions to use the SDK.
2. `dev-docs/` holds maintainer workflows and decision history. It is linked from
   the contributor guide, outside the user documentation site's navigation.
3. Changes to public contracts belong in the user reference as well as the relevant
   ADR. Explain the current behavior in the reference; preserve its rationale and
   alternatives in the ADR.
