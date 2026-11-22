#!/usr/bin/env python3
"""Compile the patched MUX logic against an isolated ACPI fixture."""

from pathlib import Path
import subprocess
import sys
import tempfile


source = (Path(sys.argv[1]) / "kexts/NVRM/NVRM.cpp").read_text()
state = source[source.index("struct LoqPanelState"):source.index("#define NVRM_MAX_HEADS")]
start = source.index("static IOACPIPlatformDevice *loqLcdDevice()")
logic = source[start:source.index("// Linux order (nvidia_suspend)", start)]
fixture = Path(__file__).with_name("loq_panel_fixture.cpp").read_text()
test = fixture.replace("// LOQ_PANEL_STATE", state).replace("// LOQ_PANEL_IMPLEMENTATION", logic)

with tempfile.TemporaryDirectory(prefix="loq-s3-test-") as tmp:
    code = Path(tmp) / "test.cpp"
    binary = Path(tmp) / "test"
    code.write_text(test)
    subprocess.run(["xcrun", "clang++", "-std=c++17", str(code), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
