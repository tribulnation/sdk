<!-- github-only -->
<table><tr>
<td align="center"><a href="../index.md">Docs</a></td>
<td align="center"><b>Market</b></td>
<td align="center"><a href="../earn/index.md">Earn</a></td>
<td align="center"><a href="../wallet/index.md">Wallet</a></td>
<td align="center"><a href="../report/index.md">Report</a></td>
<td align="center"><a href="../reference/index.md">Reference</a></td>
<td align="center"><a href="https://tribulnation.com/sdk/docs/support">Support matrix</a></td>
</tr></table>
<!-- /github-only -->

# Streaming

`depth_stream()` and `trades_stream()` are async context managers yielding an async
iterable. A venue fans a single shared upstream out to every subscriber through a
*bounded per-subscriber queue*, controlled by two arguments:

- **`queue_size`** — how many items to buffer for *this* subscriber.
- **`overflow`** — what happens when that buffer is full:
  - `'latest'` — keep only the newest item; a slow consumer silently skips stale ones.
  - `'fail'` — fail the subscriber with a `NetworkError` so the caller can reconnect,
    rather than dropping data silently.

The defaults reflect each stream's intent:

| Stream | `queue_size` | `overflow` | Rationale |
| --- | --- | --- | --- |
| `depth_stream` | `1` | `'latest'` | You only care about the freshest book. |
| `trades_stream` | `1000` | `'fail'` | Don't drop your own fills silently. |

To capture *every* book (e.g. recording full depth history), pass `overflow='fail'` with a
larger `queue_size`.

The polling fallback used by generic markets has no shared upstream to fan out, so it
ignores `queue_size`/`overflow`; native venue subscriptions honor them.

<!-- next -->

---

← [Collateral & Risk Management](collateral.md) · **Next:** [Implementations](implementations/index.md) →

<!-- /next -->
