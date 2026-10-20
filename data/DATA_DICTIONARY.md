# Input schema and dataset conventions

The data is **100% synthetic and fictional**. Dates and source names are invented test material, not actual customer records.

| Column | Type | Meaning / use |
|---|---|---|
| `row_id` | string | Unique immutable ingestion-row identifier. Used as a deterministic tie-break for repeated `event_id`. |
| `event_id` | string | Logical event identifier; duplicated, conflicted, or missing in some rows. Trim; case-sensitive. |
| `order_id` | string | Order identifier. Sometimes missing. Trim; case-sensitive. |
| `event_type` | string | Proposed state change. Can have whitespace, lowercase values, or unknown labels. Trim + uppercase. |
| `event_time` | string | Time event occurred. Some values invalid or missing; mixed supported UTC representations. Primary chronological key. |
| `received_at` | string | When upstream system logged/received event. Informational only, *not* chronological key. |
| `source_system` | string | Web, payment, warehouse, courier, returns, etc. Informational only. |
| `metadata` | string | Arbitrary synthetic text; **not** used by required engine. |

Important invariants: `row_id` is unique in each file; input row order is untrustworthy; `received_at` can be very late; record duplication is about repeated **nonempty event_id**, not identical full CSV rows.

Supported `event_time` forms: `YYYY-MM-DDTHH:MM:SSZ`, `YYYY-MM-DD HH:MM:SS`, and `YYYY-MM-DDTHH:MM:SS+00:00`. Unzoned timestamps are UTC. Work with seconds precision; output UTC with `Z`.

Data has varied order lifecycle lengths, including partial orders, cancellations, delivery, and returns/refunds. It includes seeded duplicates, reused IDs, invalid transitions, unexpected statuses, missing keys, empty/bad timestamps, equal timestamps and ingestion delays.

A small `debug_subset.csv` is intended for smoke tests; use `order_events.csv` for the full run.

**Strict timestamp formats:** Only the three full-second UTC representations above are valid. For example, date-only values, nonzero timezone offsets, timestamps missing seconds, and fractional seconds are invalid, even if a permissive Python date parser would accept them.

The informational `metadata` and `source_system` columns must **not** be used to determine anomaly labels or canonical event identity.

**Identifier interpretation:** `order_id`, `event_id`, and `row_id` are opaque strings. Their prefixes and numeric-looking portions are not semantic labels; do not infer validity, event type, or anomaly class from identifier naming.
