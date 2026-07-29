<!-- vendored from workspace/.agents/rules/typescript.md — do not edit; run `python scripts/sync.py agents` -->
# TypeScript Guidelines

### Type Definitions

- Always use `type`, not `interface`
- No semicolons
- Use the style below for record unions

  ```typescript
  type User = {
    id: string
    name: string
    email: string
  } | {
    id: string
  }
  ```
