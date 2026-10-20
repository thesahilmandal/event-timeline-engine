import csv
import os
import random
import sys
import tempfile
import unittest
from copy import deepcopy
from typing import Dict, List, Tuple
from unittest.mock import patch

# Adjust path to import main.py from the parent directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
try:
    import main
except ImportError:
    raise ImportError("Could not import main.py. Ensure test_main.py is in the tests/ directory and main.py is in the root.")


class TestEventTimelineEngine(unittest.TestCase):
    """
    Comprehensive test suite for the Event Timeline Reconstruction Engine.
    Validates CSV parsing, duplicate detection, validation precedence, chronological 
    reconstruction, business state transitions, and deterministic outputs.
    """

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.input_csv = os.path.join(self.temp_dir.name, 'input.csv')
        self.output_dir = os.path.join(self.temp_dir.name, 'output')
        os.makedirs(self.output_dir, exist_ok=True)
        
        self.default_row = {
            "row_id": "",
            "event_id": "",
            "order_id": "",
            "event_type": "",
            "event_time": "",
            "received_at": "2026-01-01T00:00:00Z",
            "source_system": "TEST",
            "metadata": ""
        }

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_csv(self, rows: List[Dict[str, str]], filepath: str) -> None:
        fieldnames = ["row_id", "event_id", "order_id", "event_type", "event_time", "received_at", "source_system", "metadata"]
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                full_row = {**self.default_row, **row}
                writer.writerow(full_row)

    def _read_csv(self, filepath: str) -> List[Dict[str, str]]:
        with open(filepath, 'r', encoding='utf-8') as f:
            return list(csv.DictReader(f))

    def _run_engine(self, rows: List[Dict[str, str]]) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
        """Writes rows to a temporary CSV, runs the engine, and returns (summaries, anomalies)."""
        self._write_csv(rows, self.input_csv)
        
        test_args = ['main.py', '--input', self.input_csv, '--output-dir', self.output_dir]
        with patch.object(sys, 'argv', test_args):
            main.main()
            
        summary_path = os.path.join(self.output_dir, "order_summary.csv")
        anomalies_path = os.path.join(self.output_dir, "anomalies.csv")
        
        summaries = self._read_csv(summary_path) if os.path.exists(summary_path) else []
        anomalies = self._read_csv(anomalies_path) if os.path.exists(anomalies_path) else []
        return summaries, anomalies

    def test_cli_arguments_missing_input(self) -> None:
        """Test that the CLI correctly requires arguments and exits on missing file."""
        test_args = ['main.py', '--input', 'non_existent_file.csv', '--output-dir', self.output_dir]
        with patch.object(sys, 'argv', test_args):
            with self.assertRaises(SystemExit):
                main.main()

    def test_valid_timeline_reconstruction(self) -> None:
        """Test a fully valid timeline from START to DELIVERED with out-of-order rows."""
        rows = [
            {"row_id": "3", "event_id": "E3", "order_id": "O1", "event_type": "PACKED", "event_time": "2026-01-01T12:00:00Z"},
            {"row_id": "1", "event_id": "E1", "order_id": "O1", "event_type": "PLACED", "event_time": "2026-01-01T10:00:00Z"},
            {"row_id": "4", "event_id": "E4", "order_id": "O1", "event_type": "SHIPPED", "event_time": "2026-01-01T13:00:00Z"},
            {"row_id": "2", "event_id": "E2", "order_id": "O1", "event_type": "PAID", "event_time": "2026-01-01T11:00:00Z"},
            {"row_id": "5", "event_id": "E5", "order_id": "O1", "event_type": "OUT_FOR_DELIVERY", "event_time": "2026-01-01T14:00:00Z"},
            {"row_id": "6", "event_id": "E6", "order_id": "O1", "event_type": "DELIVERED", "event_time": "2026-01-01T15:00:00Z"}
        ]
        summaries, anomalies = self._run_engine(rows)
        
        self.assertEqual(len(anomalies), 0)
        self.assertEqual(len(summaries), 1)
        
        s = summaries[0]
        self.assertEqual(s["order_id"], "O1")
        self.assertEqual(s["final_status"], "DELIVERED")
        self.assertEqual(s["valid_events"], "6")
        self.assertEqual(s["anomaly_count"], "0")
        self.assertEqual(s["first_valid_event_time"], "2026-01-01T10:00:00Z")
        self.assertEqual(s["last_valid_event_time"], "2026-01-01T15:00:00Z")

    def test_invalid_transitions(self) -> None:
        """Test that invalid state transitions are ignored and reported, while valid ones continue."""
        rows = [
            {"row_id": "1", "event_id": "E1", "order_id": "O1", "event_type": "PLACED", "event_time": "2026-01-01T10:00:00Z"},
            {"row_id": "2", "event_id": "E2", "order_id": "O1", "event_type": "DELIVERED", "event_time": "2026-01-01T11:00:00Z"}, # Invalid jump
            {"row_id": "3", "event_id": "E3", "order_id": "O1", "event_type": "PAID", "event_time": "2026-01-01T12:00:00Z"},
        ]
        summaries, anomalies = self._run_engine(rows)
        
        self.assertEqual(len(anomalies), 1)
        self.assertEqual(anomalies[0]["row_id"], "2")
        self.assertEqual(anomalies[0]["anomaly_type"], "INVALID_TRANSITION")
        
        s = summaries[0]
        self.assertEqual(s["final_status"], "PAID")
        self.assertEqual(s["valid_events"], "2") # PLACED, PAID
        self.assertEqual(s["anomaly_count"], "1")

    def test_canonical_row_selection_and_conflicts(self) -> None:
        """Test lexicographical row_id canonical selection, DUPLICATE_EVENT, and EVENT_ID_CONFLICT."""
        rows = [
            # "10" is lexicographically smaller than "2" and "A"
            {"row_id": "2", "event_id": "E1", "order_id": "O1", "event_type": "PLACED", "event_time": "2026-01-01T10:00:00Z"}, # DUPLICATE_EVENT
            {"row_id": "10", "event_id": "E1", "order_id": "O1", "event_type": "PLACED", "event_time": "2026-01-01T10:00:00Z"}, # CANONICAL
            {"row_id": "A", "event_id": "E1", "order_id": "O1", "event_type": "PAID", "event_time": "2026-01-01T10:00:00Z"}, # EVENT_ID_CONFLICT
        ]
        summaries, anomalies = self._run_engine(rows)
        
        self.assertEqual(len(anomalies), 2)
        
        # Verify anomalies are sorted by row_id ascending
        self.assertEqual(anomalies[0]["row_id"], "2")
        self.assertEqual(anomalies[0]["anomaly_type"], "DUPLICATE_EVENT")
        self.assertEqual(anomalies[1]["row_id"], "A")
        self.assertEqual(anomalies[1]["anomaly_type"], "EVENT_ID_CONFLICT")
        
        # Summary should only have 1 valid event (the canonical one)
        s = summaries[0]
        self.assertEqual(s["valid_events"], "1")
        self.assertEqual(s["anomaly_count"], "2")

    def test_validation_precedence(self) -> None:
        """Test that single-row validation follows the strict precedence rules."""
        # Precedence: MISSING_ORDER_ID > MISSING_EVENT_ID > MISSING_TIMESTAMP > INVALID_TIMESTAMP > UNKNOWN_EVENT
        
        rows = [
            # Misses all, should be MISSING_ORDER_ID
            {"row_id": "1", "event_id": "", "order_id": "", "event_type": "UNKNOWN", "event_time": ""},
            # Has order, misses event, should be MISSING_EVENT_ID
            {"row_id": "2", "event_id": "", "order_id": "O1", "event_type": "UNKNOWN", "event_time": ""},
            # Has order/event, misses time, should be MISSING_TIMESTAMP
            {"row_id": "3", "event_id": "E3", "order_id": "O1", "event_type": "UNKNOWN", "event_time": "   "},
            # Has order/event/time, bad time, should be INVALID_TIMESTAMP
            {"row_id": "4", "event_id": "E4", "order_id": "O1", "event_type": "UNKNOWN", "event_time": "not-a-date"},
            # Has order/event/time(valid), bad type, should be UNKNOWN_EVENT
            {"row_id": "5", "event_id": "E5", "order_id": "O1", "event_type": "GARBAGE", "event_time": "2026-01-01T10:00:00Z"},
        ]
        
        _, anomalies = self._run_engine(rows)
        self.assertEqual(len(anomalies), 5)
        
        anomaly_types = {a["row_id"]: a["anomaly_type"] for a in anomalies}
        self.assertEqual(anomaly_types["1"], "MISSING_ORDER_ID")
        self.assertEqual(anomaly_types["2"], "MISSING_EVENT_ID")
        self.assertEqual(anomaly_types["3"], "MISSING_TIMESTAMP")
        self.assertEqual(anomaly_types["4"], "INVALID_TIMESTAMP")
        self.assertEqual(anomaly_types["5"], "UNKNOWN_EVENT")

    def test_timestamp_parsing_and_utc_normalization(self) -> None:
        """Test the 3 supported UTC formats and rejection of invalid ones."""
        rows = [
            {"row_id": "1", "event_id": "E1", "order_id": "O1", "event_type": "PLACED", "event_time": "2026-01-01T10:00:00Z"},
            {"row_id": "2", "event_id": "E2", "order_id": "O1", "event_type": "PAID", "event_time": "2026-01-01 11:00:00"},
            {"row_id": "3", "event_id": "E3", "order_id": "O1", "event_type": "PACKED", "event_time": "2026-01-01T12:00:00+00:00"},
            {"row_id": "4", "event_id": "E4", "order_id": "O1", "event_type": "SHIPPED", "event_time": "2026-01-01T13:00Z"}, # Invalid (missing seconds)
        ]
        summaries, anomalies = self._run_engine(rows)
        
        self.assertEqual(len(anomalies), 1)
        self.assertEqual(anomalies[0]["row_id"], "4")
        self.assertEqual(anomalies[0]["anomaly_type"], "INVALID_TIMESTAMP")
        
        s = summaries[0]
        self.assertEqual(s["valid_events"], "3")
        self.assertEqual(s["first_valid_event_time"], "2026-01-01T10:00:00Z")
        self.assertEqual(s["last_valid_event_time"], "2026-01-01T12:00:00Z")

    def test_anomaly_accounting_and_empty_order_ids(self) -> None:
        """Test that empty order IDs don't get summaries and don't attribute anomaly counts to a blank order."""
        rows = [
            {"row_id": "1", "event_id": "E1", "order_id": "O1", "event_type": "PLACED", "event_time": "2026-01-01T10:00:00Z"},
            {"row_id": "2", "event_id": "E2", "order_id": "O1", "event_type": "GARBAGE", "event_time": "2026-01-01T10:00:00Z"},
            {"row_id": "3", "event_id": "E3", "order_id": "", "event_type": "GARBAGE", "event_time": "2026-01-01T10:00:00Z"}, # Empty order ID
        ]
        summaries, anomalies = self._run_engine(rows)
        
        self.assertEqual(len(anomalies), 2)
        
        # Summary should only contain O1, not an empty string key
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0]["order_id"], "O1")
        self.assertEqual(summaries[0]["anomaly_count"], "1") # Only row 2 belongs to O1

    def test_chronological_tiebreakers(self) -> None:
        """Test that same-time events are deterministically sorted by event_id, then row_id."""
        # PLACED and PAID have the exact same time.
        # To make PLACED process first, its event_id must be lexicographically smaller.
        rows = [
            {"row_id": "1", "event_id": "B_PAID", "order_id": "O1", "event_type": "PAID", "event_time": "2026-01-01T10:00:00Z"},
            {"row_id": "2", "event_id": "A_PLACED", "order_id": "O1", "event_type": "PLACED", "event_time": "2026-01-01T10:00:00Z"},
        ]
        summaries, anomalies = self._run_engine(rows)
        
        self.assertEqual(len(anomalies), 0)
        self.assertEqual(summaries[0]["final_status"], "PAID")
        self.assertEqual(summaries[0]["valid_events"], "2")

    def test_deterministic_shuffling(self) -> None:
        """Test that the engine produces identical output regardless of input row order."""
        rows = [
            {"row_id": "1", "event_id": "E1", "order_id": "O1", "event_type": "PLACED", "event_time": "2026-01-01T10:00:00Z"},
            {"row_id": "2", "event_id": "E2", "order_id": "O1", "event_type": "PAID", "event_time": "2026-01-01T11:00:00Z"},
            {"row_id": "3", "event_id": "E1", "order_id": "O1", "event_type": "PLACED", "event_time": "2026-01-01T10:00:00Z"}, # DUPLICATE
            {"row_id": "4", "event_id": "E4", "order_id": "O2", "event_type": "INVALID", "event_time": "2026-01-01T10:00:00Z"},
            {"row_id": "5", "event_id": "E5", "order_id": "O2", "event_type": "PLACED", "event_time": "2026-01-01T12:00:00Z"},
        ]
        
        # Run 1
        sum1, ano1 = self._run_engine(rows)
        
        # Run 2 with shuffled input
        shuffled_rows = deepcopy(rows)
        random.seed(42)
        random.shuffle(shuffled_rows)
        sum2, ano2 = self._run_engine(shuffled_rows)
        
        self.assertEqual(sum1, sum2)
        self.assertEqual(ano1, ano2)

    def test_missing_and_whitespace_normalization(self) -> None:
        """Test that whitespace is trimmed and empty cells are treated as missing."""
        rows = [
            {"row_id": " 1 ", "event_id": " E1 ", "order_id": " O1 ", "event_type": " placed ", "event_time": " 2026-01-01T10:00:00Z "},
            {"row_id": "2", "event_id": "   ", "order_id": "O1", "event_type": "PAID", "event_time": "2026-01-01T11:00:00Z"}
        ]
        summaries, anomalies = self._run_engine(rows)
        
        self.assertEqual(len(anomalies), 1)
        self.assertEqual(anomalies[0]["row_id"], "2")
        self.assertEqual(anomalies[0]["anomaly_type"], "MISSING_EVENT_ID")
        
        s = summaries[0]
        self.assertEqual(s["order_id"], "O1") # Verify whitespace trimmed
        self.assertEqual(s["final_status"], "PLACED") # Verify lowercase handled

    def test_unknown_status_for_rejected_orders(self) -> None:
        """Test that an order with only rejected events appears in the summary as UNKNOWN."""
        rows = [
            {"row_id": "1", "event_id": "E1", "order_id": "O1", "event_type": "GARBAGE", "event_time": "2026-01-01T10:00:00Z"}
        ]
        summaries, anomalies = self._run_engine(rows)
        
        self.assertEqual(len(anomalies), 1)
        self.assertEqual(len(summaries), 1)
        
        s = summaries[0]
        self.assertEqual(s["order_id"], "O1")
        self.assertEqual(s["final_status"], "UNKNOWN")
        self.assertEqual(s["valid_events"], "0")
        self.assertEqual(s["first_valid_event_time"], "")
        self.assertEqual(s["last_valid_event_time"], "")

    def test_worked_example_integration(self) -> None:
        """
        Integration test: If the provided worked example files are present in the dataset folder,
        validate that the engine produces the exact expected anomaly and summary CSVs.
        """
        data_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data'))
        input_csv = os.path.join(data_dir, 'worked_example_input.csv')
        expected_summary = os.path.join(data_dir, 'worked_example_summary.csv')
        expected_anomalies = os.path.join(data_dir, 'worked_example_anomalies.csv')
        
        if not (os.path.exists(input_csv) and os.path.exists(expected_summary) and os.path.exists(expected_anomalies)):
            self.skipTest("Worked example datasets not found in ../data. Skipping integration test.")
            
        test_args = ['main.py', '--input', input_csv, '--output-dir', self.output_dir]
        with patch.object(sys, 'argv', test_args):
            main.main()
            
        act_summary = self._read_csv(os.path.join(self.output_dir, 'order_summary.csv'))
        exp_summary = self._read_csv(expected_summary)
        
        self.assertEqual(act_summary, exp_summary, "Generated order_summary does not match worked_example_summary.csv")
        
        act_anomalies = self._read_csv(os.path.join(self.output_dir, 'anomalies.csv'))
        exp_anomalies = self._read_csv(expected_anomalies)
        
        self.assertEqual(len(act_anomalies), len(exp_anomalies), "Mismatch in number of anomalies.")
        
        for act, exp in zip(act_anomalies, exp_anomalies):
            self.assertEqual(act["row_id"], exp["row_id"])
            self.assertEqual(act["order_id"], exp["order_id"])
            self.assertEqual(act["event_id"], exp["event_id"])
            self.assertEqual(act["anomaly_type"], exp["anomaly_type"])
            # We ignore the 'details' text field as per prompt instructions, just checking core logic


if __name__ == '__main__':
    unittest.main()