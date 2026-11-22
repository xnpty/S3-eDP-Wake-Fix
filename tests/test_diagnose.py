#!/usr/bin/env python3
"""Verify that one wake report never borrows results from another sleep cycle."""

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from diagnose import analyze_wake, parse_events, read_wake_report


GOOD_RM = "NVRM-xnu: rm_power_management(RESUME) -> 0x0, user channels restarted -> 0x0"
BAD_RM = "NVRM-xnu: rm_power_management(RESUME) -> 0x56, user channels restarted -> 0x56"
MODESET_OK = "NVRM-fb: display wake: head 0 mode and surface committed again -> ok (rc 0)"
MODESET_FAILED = "NVRM-fb: display wake: head 0 mode and surface committed again -> FAILED (rc -4)"


def events(*messages, boot="boot-1"):
    return [{"eventMessage": message, "bootUUID": boot} for message in messages]


class WakeDiagnosisTest(unittest.TestCase):
    def test_reports_loq_mux_transition_and_the_last_result_per_head(self):
        report = analyze_wake(events(
            "NVRM-xnu: LOQ S3 eDP before sleep: mode 2 route 2 reset 2",
            "ACPI SLEEP", "ACPI S3 WAKE", "AppleACPIPlatformPower Wake reason: RTC XDCI CNVW (Alarm)",
            "NVRM-xnu: LOQ S3 eDP after wake: mode 2 route 1 reset 2",
            "NVRM-xnu: LOQ S3 eDP discrete route restore: 0x0, route 2",
            GOOD_RM, MODESET_FAILED, MODESET_OK,
        ))
        self.assertEqual(report.state, "S3")
        self.assertEqual(report.mux_before, (2, 2, 2))
        self.assertEqual(report.mux_after, (2, 1, 2))
        self.assertEqual(report.route_restore, (0, 2))
        self.assertEqual(report.wake_sources, ("RTC", "XDCI", "CNVW"))
        self.assertEqual(report.modesets, {0: (True, 0)})

    def test_routes_a_desktop_failure_to_gpu_or_display(self):
        report = analyze_wake(events("ACPI S3 WAKE", BAD_RM))
        self.assertIn("PCIe and GSP", report.finding("dp", "dark"))
        report = analyze_wake(events("ACPI S3 WAKE", GOOD_RM, MODESET_FAILED))
        self.assertIn("display modeset failed", report.finding("dp", "dark"))
        report = analyze_wake(events("ACPI S3 WAKE", GOOD_RM, MODESET_OK))
        self.assertIn("DP output link", report.finding("dp", "dark"))

    def test_keeps_the_most_recent_s0_wake(self):
        report = analyze_wake(events("ACPI S3 WAKE", GOOD_RM, MODESET_OK, "ACPI SLEEP", "ACPI S0 WAKE"))
        self.assertEqual(report.state, "S0")
        self.assertFalse(report.resume)
        self.assertFalse(report.modesets)

    def test_does_not_attribute_the_previous_wake_to_an_unfinished_sleep(self):
        report = analyze_wake(events("ACPI S3 WAKE", GOOD_RM, MODESET_OK, "ACPI SLEEP"))
        self.assertTrue(report.entered_sleep)
        self.assertFalse(report.state)
        self.assertFalse(report.resume)

    def test_does_not_use_later_results_from_another_boot(self):
        report = analyze_wake(events("ACPI S3 WAKE") + events(GOOD_RM, MODESET_OK, boot="boot-2"))
        self.assertFalse(report.resume)
        self.assertFalse(report.modesets)

    def test_ignores_log_metadata_when_there_is_no_observed_wake(self):
        report = analyze_wake(parse_events(b'{"finished":true}\n'))
        self.assertFalse(report.state)
        self.assertIn("no ACPI", report.finding("hdmi", "unknown"))

    def test_finds_the_latest_wake_without_scanning_older_windows(self):
        def ndjson(*messages):
            return "\n".join(json.dumps(event) for event in events(*messages)).encode()

        with patch("diagnose.read_command", side_effect=(
            ndjson(MODESET_OK),
            ndjson("ACPI S3 WAKE", GOOD_RM),
        )) as command:
            report = read_wake_report("1d")
        self.assertEqual(command.call_count, 2)
        self.assertEqual(report.state, "S3")
        self.assertEqual(report.resume, (0, 0))
        self.assertEqual(report.modesets, {0: (True, 0)})


if __name__ == "__main__":
    unittest.main()
