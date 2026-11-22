#!/usr/bin/env python3
"""Read a recent macOS sleep/wake trace and summarize NVIDIA wake progress."""

import argparse
from dataclasses import dataclass, field
import json
import os
import plistlib
import re
import subprocess
import time


WAKE = re.compile(r"ACPI (S[0-5]) WAKE")
RESUME = re.compile(
    r"rm_power_management\(RESUME\) -> (0x[\da-fA-F]+), "
    r"user channels restarted -> (0x[\da-fA-F]+)"
)
MODESET = re.compile(r"display wake: head (\d+) mode and surface committed again -> (ok|FAILED) \(rc (-?\d+)\)")
MUX = re.compile(r"LOQ S3 eDP (before sleep|after wake): mode (\d+) route (\d+) reset (\d+)")
RESTORED = re.compile(r"LOQ S3 eDP discrete route restore: (0x[\da-fA-F]+), route (\d+)")
LOADED = re.compile(
    r"\bcom\.nullmoth\.(NVRM|NVAccel|NVRMFB|NVRMAGDC) \(([\d.]+)\) "
    r"([A-Fa-f0-9-]{36})\b"
)
PREDICATE = (
    'process == "kernel" AND (eventMessage == "ACPI SLEEP" OR '
    '(eventMessage BEGINSWITH "ACPI S" AND eventMessage ENDSWITH " WAKE") OR '
    'eventMessage CONTAINS "rm_power_management(RESUME)" OR '
    'eventMessage CONTAINS "display wake: head" OR '
    'eventMessage CONTAINS "LOQ S3 eDP" OR '
    'eventMessage CONTAINS "AppleACPIPlatformPower Wake reason:")'
)


@dataclass
class WakeReport:
    state: str = ""
    entered_sleep: bool = False
    resume: tuple = ()
    modesets: dict = field(default_factory=dict)
    mux_before: tuple = ()
    mux_after: tuple = ()
    route_restore: tuple = ()
    wake_sources: tuple = ()

    def finding(self, connector, screen):
        if self.state != "S3":
            if self.state:
                return f"The most recent recorded wake is ACPI {self.state}."
            if self.entered_sleep:
                return "The log records sleep entry and has no later ACPI wake marker."
            return "The selected log window has no ACPI sleep or wake marker."
        if not self.resume:
            return "S3 wake is recorded. The log has no NVRM GPU resume result."
        if self.resume[0]:
            return "NVRM reported a GPU resume error. Check PCIe and GSP recovery."
        if self.resume[1]:
            return "The GPU resumed and NVRM reported a user-channel restart error."
        if any(not ok for ok, _ in self.modesets.values()):
            return "The GPU resumed and at least one latest display modeset failed."
        if not self.modesets:
            return "The GPU resumed. The log has no NVRMFB modeset result for this wake."
        if screen == "dark":
            if connector == "edp":
                return "GPU resume and modeset succeeded in the log. Check panel power and the eDP AUX link."
            if connector in ("dp", "hdmi"):
                return f"GPU resume and modeset succeeded in the log. Check the {connector.upper()} output link."
            return "GPU resume and modeset succeeded in the log. Identify the display connector and check its link."
        return "GPU resume and recorded display modesets succeeded."


def read_command(*args):
    return subprocess.run(args, capture_output=True, timeout=45, check=True).stdout


def parse_events(data):
    events = []
    for line in data.splitlines():
        if line.startswith(b"{"):
            event = json.loads(line)
            if isinstance(event.get("eventMessage"), str):
                events.append(event)
    return events


def analyze_wake(events):
    for index in range(len(events) - 1, -1, -1):
        event = events[index]
        message = event["eventMessage"]
        if message == "ACPI SLEEP":
            return WakeReport(entered_sleep=True)
        if marker := WAKE.fullmatch(message):
            break
    else:
        return WakeReport()

    boot = event.get("bootUUID")
    report = WakeReport(state=marker[1])
    for earlier in reversed(events[:index]):
        message = earlier["eventMessage"]
        if earlier.get("bootUUID") != boot or WAKE.fullmatch(message):
            break
        if (mux := MUX.search(message)) and mux[1] == "before sleep":
            report.mux_before = tuple(map(int, mux.groups()[1:]))
            break
    for later in events[index + 1:]:
        if later.get("bootUUID") != boot:
            break
        message = later["eventMessage"]
        if result := RESUME.search(message):
            report.resume = tuple(int(value, 16) for value in result.groups())
        elif mode := MODESET.search(message):
            report.modesets[int(mode[1])] = (mode[2] == "ok", int(mode[3]))
        elif (mux := MUX.search(message)) and mux[1] == "after wake":
            report.mux_after = tuple(map(int, mux.groups()[1:]))
        elif route := RESTORED.search(message):
            report.route_restore = (int(route[1], 16), int(route[2]))
        elif "AppleACPIPlatformPower Wake reason:" in message:
            reason = message.split("Wake reason:", 1)[1].split()
            report.wake_sources = tuple(token for token in reason if re.fullmatch(r"[A-Z0-9_]{1,12}", token))
    return report


def read_wake_report(window):
    end = int(time.time()) + 1
    if window == "boot":
        raw = read_command("/usr/sbin/sysctl", "-n", "kern.boottime")
        stamp = re.search(rb"\bsec\s*=\s*(\d+)", raw)
        if not stamp:
            raise ValueError("Invalid boot timestamp")
        start = int(stamp[1])
    else:
        units = {"m": 60, "h": 3600, "d": 86400}
        start = end - int(window[:-1]) * units[window[-1]]

    # Search recent logs first. A full day of unified logs can be slow even
    # when the newest usable wake is a few minutes old.
    events = []
    for upper in range(end, start, -3600):
        lower = max(start, upper - 3600)
        data = read_command(
            "/usr/bin/log", "show", "--start", f"@{lower}", "--end", f"@{upper}",
            "--style", "ndjson", "--predicate", PREDICATE,
        )
        events[:0] = parse_events(data)
        report = analyze_wake(events)
        if report.state or report.entered_sleep:
            return report
    return WakeReport()


def display_adapters(nodes):
    adapters = []
    for node in nodes:
        keys = ("class-code", "vendor-id", "device-id", "subsystem-vendor-id", "subsystem-id")
        values = [node.get(key, b"") for key in keys]
        if not all(isinstance(value, bytes) and len(value) <= 4 for value in values):
            continue
        pci_class, vendor, device, subvendor, subsystem = [int.from_bytes(value, "little") for value in values]
        if pci_class >> 16 != 3 or not vendor or not device:
            continue
        identity = f"{vendor:04x}:{device:04x}"
        if subvendor and subsystem:
            identity += f" (subsystem {subvendor:04x}:{subsystem:04x})"
        adapters.append(identity)
    return adapters


def print_report(report, connector, screen):
    print(f"Connector {connector}, physical screen {screen}")
    print(f"ACPI wake state {report.state or 'not recorded'}")
    if report.wake_sources:
        print(f"Wake sources {', '.join(report.wake_sources)}")
    if report.resume:
        rm, channels = report.resume
        print(f"NVRM resume {rm:#x}, restart user channels {channels:#x}")
    for head, (ok, rc) in sorted(report.modesets.items()):
        print(f"NVRMFB head {head} {'ok' if ok else 'failed'} (rc {rc})")
    for label, state in (("before sleep", report.mux_before), ("after wake", report.mux_after)):
        if state:
            mode, route, reset = state
            print(f"LOQ eDP {label}, mode {mode}, route {route}, reset {reset}")
    if report.route_restore:
        status, route = report.route_restore
        print(f"LOQ route restore status {status:#x}, route {route}")
    print(report.finding(connector, screen))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--last", default="2h", help="Log window, such as 30m, 2h or boot (default 2h)")
    parser.add_argument("--connector", choices=("edp", "dp", "hdmi", "unknown"), default="unknown")
    parser.add_argument("--screen", choices=("working", "dark", "unknown"), default="unknown")
    args = parser.parse_args()
    if args.last != "boot" and not re.fullmatch(r"[1-9]\d?[mhd]", args.last):
        parser.error("--last must be boot or a duration such as 30m or 2h")
    if os.uname().sysname != "Darwin":
        parser.error("This report reads macOS logs.")

    macos_version = read_command("/usr/bin/sw_vers", "-productVersion").decode().strip()
    macos_build = read_command("/usr/bin/sw_vers", "-buildVersion").decode().strip()
    print(f"macOS {macos_version} ({macos_build}), {os.uname().machine}")
    nodes = plistlib.loads(read_command("/usr/sbin/ioreg", "-a", "-r", "-c", "IOPCIDevice", "-d", "1"))
    adapters = display_adapters(nodes)
    print(f"PCI display adapters {', '.join(adapters) or 'none reported'}")
    try:
        kexts = read_command("/usr/bin/kmutil", "showloaded", "--list-only").decode(errors="replace")
    except (OSError, subprocess.SubprocessError):
        print("Loaded kext identities unavailable.")
    else:
        for name, version, uuid in LOADED.findall(kexts):
            print(f"{name} {version} {uuid}")

    print_report(read_wake_report(args.last), args.connector, args.screen)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise SystemExit(f"S3 wake report unavailable ({type(error).__name__}).") from None
