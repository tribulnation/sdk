# Run the shared lint on all package sources.
lint:
  ruff check --config .agents/tools/python/ruff.toml sdk/src impl/*/src

# Check the Typed Client type surface impl/ depends on; lists what was skipped.
type-surface:
  .venv/bin/python -m pytest test/test_type_surface.py -rs
