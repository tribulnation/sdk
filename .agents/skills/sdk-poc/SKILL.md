---
name: sdk-poc
description: Build or extend a venue PoC script under packages/impl/<venue>/poc/ that maps a typed client (typed_<venue>) onto an SDK surface (earn, wallet, report, market). Use whenever asked to map, prototype, PoC or verify a venue against the SDK, or to turn a PoC into an implementation. Sets the rules on live execution, forbidden workarounds, and how typed-client issues are reported.
---

# SDK PoC

A PoC script proves, method by method, that a typed client can serve an SDK surface:
each abstract method is mapped onto real client calls and executed against the live
venue. It is also how bugs in the typed clients are found, so what it reports back
matters as much as what it maps.

A PoC is a `poc/<surface>.py` in jupytext's percent format: plain Python where each
`# %%` line starts a cell (`# %% [markdown]` for prose), which editors run cell by cell.
The script holds no outputs. `sdk-dev poc run` executes cells into a paired
`poc/<surface>.ipynb` beside it, which is gitignored: cells print live account data,
and one once printed an API key. Read the pair for what a cell returned; edit the script.

Two things a PoC never does: paper over a typed-client failure, or invent a number the
venue doesn't publish. A method is mapped from the venue's own figure or it is not mapped.

## Workflow

1. Scaffold, unless the script exists: `sdk-dev poc scaffold <venue> <surface>`
   (`--name <mode>` nests it under `poc/<surface>/`, `--exchange spot` for a spot-only
   venue, `--client module:Class` when the client isn't `typed_<venue>`). This writes
   one cell per abstract method with the signature copied from the SDK. Keep the
   structure; fill the bodies.
2. Enumerate before mapping: `sdk-dev poc surface <venue> [namespace...] [--grep regex]`
   lists every endpoint with its path, signature and summary. The script's Surface cell
   does the same; adjust its filter until every endpoint the mapping uses appears in it.
   Pick from this list. Do not map from memory of the client, and do not settle for a
   nearby endpoint when the list has a direct one (an order-book midpoint is not an
   index price when `symbol_price` exists).
3. Map one method per cell, then run it: `sdk-dev poc run <script> --cells N`. The
   cell's last expression displays the result, and the paired notebook is where to read
   it. Run the setup cell first in the same invocation (`--cells 1,5`). Cells count among
   code cells only, 1-based, in file order. Display what the mapping needs and nothing
   more: an endpoint that echoes credentials or account identifiers gets its result
   narrowed to the fields under test.
4. When a call fails validation, or the client has no endpoint the venue documents,
   stop mapping that method. Leave its body raising `NotImplementedError`, record the
   issue in `typed-client-issues.md` (format below), and mark the method `blocked` in
   Coverage with the entry's title. Move on to the next method.
5. Fill the Coverage table: every method gets `verified`, `empty`, `blocked`,
   `not supported` or `not attempted`, with a one-line note. `empty` means the call ran
   and the account had nothing to show; say what would populate it.
6. Run the Catalogue cell. The SDK emits venue-native IDs and `tribulnation.catalogue`
   translates them, so every asset, network or market ID a verified method returned
   must have a translation under the venue's platform. The cell lists what is missing;
   each item is an addition to make in the catalogue repo (its own skills cover
   assets, networks and platforms), never a rename on the SDK side. The venue's
   `impl.toml` declares the ID form under `[ids]` (`symbol`, `index` or `address`);
   `sdk-dev catalogue check` verifies the catalogue's keys follow it, and
   `sdk-dev catalogue coverage` runs the same diff over every configured account.
7. `sdk-dev poc check <venue>` must pass: pyright over the cells, plus the lint below.

## Rules

- **No `validate=False`.** A validation failure is the finding. Report it, don't
  bypass it. The lint fails the script on it.
- **No stand-ins.** A method maps to the venue's own figure or it is `not supported`.
  Derived approximations (midpoint for index, `equity - available` for margin, a
  free-text filter guessed from a field's naming) are workarounds with a quieter
  symptom and are treated the same way.
- **Every cell runs, or says why not.** A code cell whose paired run is missing, or
  whose source changed since it last ran, fails the lint unless it carries a
  `# not executed: <reason>` line. Order-placing and other state-changing cells are
  written and never run; the scaffold marks them. The lint checks this against the
  paired notebook, so it holds on the machine that ran the PoC; a fresh clone has no
  pair and skips it.
- **Trading methods are mapped only for venues we trade on.** Otherwise leave
  `place_order`/`cancel_*` cells as scaffolded and mark them `not attempted`.
- **Don't decide what the client's type should be.** Report what the venue sent and
  under what condition; the typed-client maintainer decides between optional, a union,
  a new literal member or a wider type.
- **Test with reality.** A mapping that was never executed against the venue is not a
  mapping. If credentials or geography make a surface untestable, mark it
  `not attempted` with the reason rather than shipping it unverified.
- **IDs are the venue's, in one form.** Pick the raw ID form once per venue, declare it
  in `impl.toml` `[ids]`, and emit it from every surface. Translation to canonical
  assets is the catalogue's job; an untranslated ID is a catalogue gap, not a reason to
  emit a friendlier string.

## Reporting a typed-client issue

Issues live in `typed-client-issues.md` at the repo root: open defects only, grouped by
client under `## typed-<venue>` (`## codegen` for the generator), each titled by the
declaration it concerns. No numbering. An entry is deleted, not marked fixed, once the
client fix is released and the cells it blocked have been re-run clean; git history is
the record. Four kinds, each needing different evidence:

1. **wrong-type**: the venue always sends a value the declared type rejects (a string
   for a `Decimal`, an object for a list). One sample settles it.
2. **absent-under-condition**: the field is missing, `null` or `''` only sometimes.
   Give the condition hypothesis (which other field correlates) and a sample from each
   branch when the account can produce both. This is the required-vs-optional case;
   the answer is not always "make it optional".
3. **missing-literal**: a value outside a `Literal`. Give the raw value and whether it
   depends on account mode (one-way vs hedge, classic vs unified).
4. **missing-endpoint**: the venue documents an endpoint the client lacks. Give the
   docs link.

An entry carries the declaration as it stands (client-relative file and line, quoted),
the evidence, and what in this repo waits on it:

~~~markdown
### `MixAccountAsset.isolatedUnrealizedPL` is `''` on crossed-margin symbols

`classic.mix.account.get` sends `''` for `isolatedUnrealizedPL` whenever the symbol's
`marginMode` is `crossed`, which the required `Decimal` rejects.

`classic/mix/account/get.py:41`:

```python
  isolatedUnrealizedPL: Decimal
```

- Kind: absent-under-condition
- Observed: `''`; isolated symbols send a number
- Condition: `marginMode == 'crossed'`
- Samples: BTCUSDT (isolated) validates; ETHUSDT and SOLUSDT (crossed) fail
- Blocks: `poc/market/classic.py` cell 19 (`perp_collateral`)
- Suggestion (unverified): discriminate on `marginMode`
~~~

`Blocks` names the script cells to re-run once the fix lands. It may also name `pkg/`
code, but only where that code transcribes the venue's own figure through a too-loose
declared type (a `Decimal(str(x))` over a `float` field, a read through `dict[str, Any]`,
a cast bridging a `str` producer to a `Literal` consumer): a typing gap the fix simplifies
away. It never names a validation bypass or a derived stand-in, because none may exist.
`Suggestion` is optional and never acted on in the PoC.

## Turning a PoC into an implementation

Only `verified` methods are implemented. `blocked` and `not supported` ones raise
`NotImplementedError` with the reason, and `impl.toml` lists exactly the implemented
methods with a `note` for the gaps. Nothing in the implementation may do what the PoC
was forbidden from doing: a `validate=False` or a stand-in in `pkg/` is the same
finding, and belongs in `typed-client-issues.md` instead.
