# Analysis Note: Event Timeline Reconstruction

## 1. Dataset & Processing Summary
The pipeline successfully processed the complete `order_events.csv` dataset. The engine reconstructed timelines for all distinct orders, aggregating valid lifecycle events while filtering out corrupted, duplicated, or logically invalid records.

* **Total Orders Processed:** 30,840
* **Total Valid Events Accepted:** 139,647
* **Total Anomalies Detected:** 42,128

### Anomaly Breakdown
The strict validation rules and state machine identified the following rejections:
* `INVALID_TRANSITION`: 13,399
* `DUPLICATE_EVENT`: 9,675
* `UNKNOWN_EVENT`: 5,338
* `EVENT_ID_CONFLICT`: 3,717
* `MISSING_TIMESTAMP`: 3,066
* `INVALID_TIMESTAMP`: 2,969
* `MISSING_EVENT_ID`: 2,397
* `MISSING_ORDER_ID`: 1,567

## 2. Interesting Edge Cases
During implementation and testing, several interesting edge cases emerged that required specific handling:

1. **The Lexicographical Canonical Tie-Breaker:** 
   The specification mandates choosing the canonical event using the "lexicographically smallest `row_id`." This means string sorting applies rather than integer sorting (e.g., `"10"` is smaller than `"2"`). Treating `row_id` strictly as an opaque string ensures deterministic behavior but can yield counterintuitive canonical rows if one assumes IDs act as sequential chronological integers.
2. **High Volume of Invalid Transitions:** 
   `INVALID_TRANSITION` was by far the most frequent anomaly (13,399 instances). The business rules dictate that invalid state changes (e.g., `PLACED` directly to `DELIVERED`) must be ignored without updating the current state. Importantly, the engine continues evaluating *subsequent* events rather than failing the entire order. This allows orders to recover their timeline if valid transitions arrive later.
3. **Ghost Anomalies (Empty Order IDs):**
   Records missing an `order_id` (1,567 instances) pose a unique accounting challenge. The pipeline flags them as `MISSING_ORDER_ID` in `anomalies.csv`, but because they cannot be tied to a specific order, they do not increment the `anomaly_count` for any row in `order_summary.csv`. The summary file strictly reports anomalies linked to known order entities.

## 3. Engineering Trade-Off: In-Memory vs. External Processing
A significant implementation decision was choosing to rely entirely on Python's standard library (in-memory lists and dictionaries) rather than introducing external data processing frameworks like Pandas, DuckDB, or PySpark. 

**The Trade-off:** 
By grouping and sorting the ~181,000 rows in memory, the solution trades theoretical infinite scalability for extreme simplicity, zero external dependencies, and minimal operational overhead. At this specific data scale, the in-memory approach is highly performant (taking only seconds to run) and makes the script universally portable across environments without complex environment configuration. However, if this pipeline were deployed to production to handle gigabytes of data or millions of rows per batch, this architecture would hit memory limits and require refactoring to use out-of-core processing or a distributed computing framework.