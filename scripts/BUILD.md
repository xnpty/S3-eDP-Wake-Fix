# Build the two kexts from source

Use an Intel macOS build host with Xcode and Python 3.9 or newer. The release was built with Xcode 26.5 (17F42). The script clones the pinned HighDelay and NVIDIA sources into a new output directory, applies the LOQ patch, builds and signs the two kexts, and records their UUIDs and checksums.

```sh
bash scripts/build.sh ./out
```

The resulting bundles are in `out/payload`. The shipped binaries and their identity are documented in `kit.json`. Compiler, SDK or signing differences can change a local rebuild's fingerprints. The installer in the release accepts the fingerprints of the shipped builds. Drivers built from different revisions need their own matching validation before deployment.

The source patch includes framebuffer regressions for EDID preservation and wake retries. `tests/test_loq_panel.py` runs the MUX state logic from the patched NVRM source against simulated ACPI responses.
