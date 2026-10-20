import argparse
import csv
import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

# --- Constants and Configuration ---

VALID_EVENT_TYPES: Set[str] = {
    "PLACED",
    "PAID",
    "PACKED",
    "SHIPPED",
    "OUT_FOR_DELIVERY",
    "DELIVERED",
    "RETURN_REQUESTED",
    "RETURNED",
    "CANCELLED",
    "REFUNDED"
}

ALLOWED_TRANSITIONS: Dict[str, Set[str]] = {
    "START": {"PLACED"},
    "PLACED": {"PAID", "CANCELLED"},
    "PAID": {"PACKED", "CANCELLED"},
    "PACKED": {"SHIPPED", "CANCELLED"},
    "SHIPPED": {"OUT_FOR_DELIVERY"},
    "OUT_FOR_DELIVERY": {"DELIVERED"},
    "DELIVERED": {"RETURN_REQUESTED", "RETURNED"},
    "RETURN_REQUESTED": {"RETURNED"},
    "RETURNED": {"REFUNDED"},
    "CANCELLED": set(),
    "REFUNDED": set()
}

# Regex to strictly match the three allowed UTC formats
TIMESTAMP_REGEX = re.compile(
    r'^(?P<fmt1>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)|'
    r'(?P<fmt2>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})|'
    r'(?P<fmt3>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00)$'
)


def parse_strict_timestamp(ts_str: str) -> Optional[str]:
    """
    Parses a strict subset of UTC timestamps.
    Returns the ISO8601 formatted string ending in 'Z' if valid, else None.
    """
    if not ts_str:
        return None

    match = TIMESTAMP_REGEX.match(ts_str)
    if not match:
        return None

    if match.group('fmt1'):
        clean_str = ts_str
    elif match.group('fmt2'):
        clean_str = ts_str.replace(' ', 'T') + 'Z'
    elif match.group('fmt3'):
        clean_str = ts_str.replace('+00:00', 'Z')
    else:
        return None

    try:
        # Validate calendar dates (e.g., catching Feb 30th)
        dt = datetime.strptime(clean_str, "%Y-%m-%dT%H:%M:%SZ")
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None


def create_anomaly(row: Dict[str, str], anomaly_type: str, details: str) -> Dict[str, str]:
    """Helper to consistently format an anomaly record."""
    return {
        "row_id": row["row_id"],
        "order_id": row["order_id"],
        "event_id": row["event_id"],
        "anomaly_type": anomaly_type,
        "details": details
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Event Timeline Reconstruction Engine")
    parser.add_argument("--input", required=True, help="Path to input CSV")
    parser.add_argument("--output-dir", required=True, help="Directory for output CSVs")
    args = parser.parse_args()

    input_file = args.input
    output_dir = args.output_dir

    if not os.path.exists(input_file):
        sys.exit(f"Error: Input file '{input_file}' does not exist.")

    os.makedirs(output_dir, exist_ok=True)

    # 1. Initialization and Data Loading
    all_orders: Set[str] = set()
    raw_rows: List[Dict[str, str]] = []

    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                sys.exit("Error: Input file is empty or missing headers.")
                
            headers = [h.strip() for h in reader.fieldnames]
            reader.fieldnames = headers

            for csv_row in reader:
                row = {}
                for k, v in csv_row.items():
                    val = v.strip() if v else ""
                    row[k] = val
                
                # Normalize event_type explicitly as requested
                if row.get("event_type"):
                    row["event_type"] = row["event_type"].upper()
                
                # Track every nonempty order_id encountered
                if row.get("order_id"):
                    all_orders.add(row["order_id"])
                    
                raw_rows.append(row)
    except Exception as e:
        sys.exit(f"Error reading input CSV: {e}")

    # 2. Event Identity & Deduplication
    events_by_id: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    valid_stage_1: List[Dict[str, str]] = []
    anomalies: List[Dict[str, str]] = []

    for row in raw_rows:
        eid = row.get("event_id")
        if eid:
            events_by_id[eid].append(row)
        else:
            # Missing event_ids are excluded from grouping and go directly to validation
            valid_stage_1.append(row)

    for eid, group in events_by_id.items():
        # Lexicographically smallest row_id serves as the canonical row
        canonical_row = min(group, key=lambda x: x["row_id"])
        canon_tuple = (canonical_row["order_id"], canonical_row["event_type"], canonical_row["event_time"])
        
        for row in group:
            if row["row_id"] == canonical_row["row_id"]:
                valid_stage_1.append(row)
            else:
                curr_tuple = (row["order_id"], row["event_type"], row["event_time"])
                if curr_tuple == canon_tuple:
                    anomalies.append(
                        create_anomaly(row, "DUPLICATE_EVENT", "Repeated event_id and matching event identity")
                    )
                else:
                    anomalies.append(
                        create_anomaly(row, "EVENT_ID_CONFLICT", "Repeated event_id with differing event identity")
                    )

    # 3. Single-Row Validation Precedence
    valid_stage_2: List[Dict[str, str]] = []

    for row in valid_stage_1:
        if not row["order_id"]:
            anomalies.append(create_anomaly(row, "MISSING_ORDER_ID", "Empty order_id"))
        elif not row["event_id"]:
            anomalies.append(create_anomaly(row, "MISSING_EVENT_ID", "Empty event_id"))
        elif not row["event_time"]:
            anomalies.append(create_anomaly(row, "MISSING_TIMESTAMP", "Empty event_time"))
        else:
            parsed_time = parse_strict_timestamp(row["event_time"])
            if not parsed_time:
                anomalies.append(
                    create_anomaly(row, "INVALID_TIMESTAMP", "Cannot parse event_time as supported UTC format")
                )
            elif row["event_type"] not in VALID_EVENT_TYPES:
                anomalies.append(create_anomaly(row, "UNKNOWN_EVENT", "Unknown/empty event_type"))
            else:
                # Event is valid, attach parsed time for deterministic sorting
                row["parsed_time"] = parsed_time
                valid_stage_2.append(row)

    # 4. Timeline Reconstruction and State Machine
    orders_data: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for row in valid_stage_2:
        orders_data[row["order_id"]].append(row)

    order_summaries: Dict[str, Dict[str, Any]] = {}

    for oid in all_orders:
        if oid not in orders_data:
            order_summaries[oid] = {
                "order_id": oid,
                "final_status": "UNKNOWN",
                "valid_events": 0,
                "anomaly_count": 0,
                "first_valid_event_time": "",
                "last_valid_event_time": ""
            }
            continue

        group = orders_data[oid]
        # Sort chronologically, deterministic tie-breaking on event_id, then row_id
        group.sort(key=lambda x: (x["parsed_time"], x["event_id"], x["row_id"]))

        state = "START"
        valid_events_count = 0
        first_time = ""
        last_time = ""

        for row in group:
            proposed_state = row["event_type"]
            if proposed_state in ALLOWED_TRANSITIONS[state]:
                state = proposed_state
                valid_events_count += 1
                if not first_time:
                    first_time = row["parsed_time"]
                last_time = row["parsed_time"]
            else:
                anomalies.append(
                    create_anomaly(row, "INVALID_TRANSITION", f"{state} -> {proposed_state} is not allowed")
                )

        final_state = state if state != "START" else "UNKNOWN"
        order_summaries[oid] = {
            "order_id": oid,
            "final_status": final_state,
            "valid_events": valid_events_count,
            "anomaly_count": 0, 
            "first_valid_event_time": first_time,
            "last_valid_event_time": last_time
        }

    # 5. Anomaly Accounting
    for anomaly in anomalies:
        oid = anomaly["order_id"]
        # Only attribute to order anomaly_count if order_id is nonempty
        if oid and oid in order_summaries:
            order_summaries[oid]["anomaly_count"] += 1

    # Sort structures for deterministic output
    anomalies.sort(key=lambda x: x["row_id"])
    sorted_order_summaries = sorted(order_summaries.values(), key=lambda x: x["order_id"])

    # 6. Export outputs
    summary_path = os.path.join(output_dir, "order_summary.csv")
    anomalies_path = os.path.join(output_dir, "anomalies.csv")

    summary_headers = [
        "order_id", "final_status", "valid_events", "anomaly_count",
        "first_valid_event_time", "last_valid_event_time"
    ]
    with open(summary_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=summary_headers)
        writer.writeheader()
        writer.writerows(sorted_order_summaries)

    anomaly_headers = ["row_id", "order_id", "event_id", "anomaly_type", "details"]
    with open(anomalies_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=anomaly_headers)
        writer.writeheader()
        writer.writerows(anomalies)


if __name__ == "__main__":
    main()