# Event Timeline Reconstruction Engine

## Overview
This project is a Python-based data pipeline designed to ingest, clean, and reconstruct the lifecycle of e-commerce orders from a messy, out-of-order event log. It handles duplicate events, conflicting records, invalid timestamps, and out-of-sequence state transitions, ultimately outputting a clean summary of each order and a detailed log of any anomalies found.

## Project Structure
```text
project/
├── data/                  # Input CSV files (omitted from version control)
├── output/                # Generated output CSVs (order_summary.csv, anomalies.csv)
├── tests/                 # Unit tests
│   ├── __init__.py
│   └── test_main.py
├── main.py                # Main executable script
├── requirements.txt       # Project dependencies (empty, standard library only)
├── analysis_note.md       # Brief analysis of findings and edge cases
└── README.md              # Project documentation

```

## Prerequisites & Dependencies

* **Python 3.10+** (Developed and thoroughly tested on **Python 3.14.2**)
* No external packages are required. The solution relies entirely on Python's robust standard library (`csv`, `datetime`, `collections`, `re`) to minimize overhead and avoid dependency issues.

## Setup and Execution

1. **Clone the repository** and navigate to the project root.
2. **Ensure your input data** (e.g., `order_events.csv`) is placed in the `data/` directory.
3. **Run the pipeline** using the following command:

```bash
python main.py --input data/order_events.csv --output-dir output

```

This command will process the input dataset and generate `order_summary.csv` and `anomalies.csv` inside the `output/` directory.

## Testing

The project includes a comprehensive suite of unit tests verifying deduplication, validation precedence, business logic, and deterministic sorting.

To run the tests, execute:

```bash
python -m unittest discover -s tests -v

```

## Implementation Approach & Design Decisions

Rather than reaching for heavy data manipulation libraries like Pandas, I opted to build this using Python's standard library. Given the dataset size (~181,000 rows), an in-memory approach using native dictionaries and lists is highly efficient and eliminates the need for external dependencies.

The pipeline processes data in distinct sequential phases:

1. **Normalization:** As the CSV is read, string fields are stripped of surrounding whitespace, and `event_type` is converted to uppercase. Empty strings are handled consistently as missing values.
2. **Event Identity & Deduplication:** To handle duplicate or conflicting `event_id`s, I grouped rows by `event_id`. The row with the lexicographically smallest `row_id` is selected as the canonical event. Any other row in the group is compared to the canonical row: identical data triggers a `DUPLICATE_EVENT`, while differing data triggers an `EVENT_ID_CONFLICT`.
3. **Row-Level Validation:** Canonical rows are checked against strict, sequential rules (missing IDs, missing/invalid timestamps, unknown events). By using `if/elif` chains, I ensured that only the *first* applicable applicable anomaly is reported for any given row, adhering to the precedence rules.
4. **Timestamp Standardization:** I implemented a strict Regex-based parser that only accepts the three allowed UTC formats, converting them into a standard `YYYY-MM-DDTHH:MM:SSZ` string. This guarantees reliable chronological sorting.
5. **Timeline Reconstruction:** Valid events are grouped by `order_id` and sorted primarily by the parsed timestamp. To guarantee deterministic results regardless of input order, `event_id` and `row_id` are used as secondary and tertiary sort keys.
6. **State Machine:** A dictionary maps each valid state to a set of allowed subsequent states. Events are evaluated chronologically. Invalid transitions are logged as anomalies and bypassed, allowing the timeline evaluation to continue with the current state intact.

## Complexity Considerations

* **Time Complexity: $O(N \log N)$**
Reading the CSV and the initial validation passes take $O(N)$ time, where $N$ is the number of rows. Grouping events takes $O(N)$ time. The most computationally expensive step is sorting the events for each order. In the worst-case scenario, sorting takes $O(N \log N)$. Therefore, the overall time complexity is bound by $O(N \log N)$.
* **Space Complexity: $O(N)$**
The script processes the file by loading parsed rows into memory (stored in dictionaries and lists). For 181,000 rows, this consumes a negligible amount of RAM (roughly 15-30 MB) on modern machines, making an $O(N)$ space complexity highly practical and fast.

## Limitations and Trade-offs

* **In-Memory Processing:** Because the script loads the dataset into memory to group and sort by `order_id`, it will not scale infinitely. If the dataset grew to tens of gigabytes, this approach would cause an Out-Of-Memory (OOM) error. A distributed framework (like PySpark) or an out-of-core database solution (like DuckDB or SQLite) would be necessary for massive scale.
* **Lexicographical Sorting:** Sorting `row_id` lexicographically means "10" comes before "2". This is explicitly required by the prompt, but in a real-world scenario where IDs are numerical, this could lead to unintuitive canonical row selection.

## Tools & AI Disclosure

* **Language:** Python 3.14.2 (Standard Library only; backwards compatible with 3.10+)
* **AI Assistance:** I utilized an AI coding assistant (LLM) during the development of this project. It acted as a technical mentor to help me break down the complex requirements, brainstorm edge-case scenarios (like the lexicographical `row_id` trap and strict timezone handling), and structure the initial boilerplate and unit tests. All final code logic, architectural decisions, and explanations represent my own understanding of the pipeline.