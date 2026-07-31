# Run the shared lint on all package sources.
lint:
  ruff check --config .agents/tools/python/ruff.toml sdk/src impl/*/src
