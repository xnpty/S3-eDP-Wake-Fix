# S3-eDP-Wake-Fix

[Hướng dẫn tiếng Việt](README.vi.md) · [Download v0.1.1](https://github.com/xnpty/S3-eDP-Wake-Fix/releases/tag/v0.1.1)

Restore the built-in display when a Lenovo LOQ with the RTX 4050 Laptop GPU wakes from ACPI S3 on macOS Tahoe. On the tested machine, the firmware switched the eDP display MUX to the iGPU during S3 resume even though the firmware was set to discrete-only. The patched NVRM restores the previously active NVIDIA route before resuming NVIDIA RM and NVKMS. NVRMFB retains the panel's valid EDID if NVIDIA temporarily reports its fallback EDID and retries a rejected wake modeset once.

## Diagnose an RTX wake problem

Use [diagnose.py](diagnose.py) on macOS after a sleep/wake attempt. It reads the GPU PCI IDs, loaded driver versions and the most recent ACPI transition in the selected log window. The report can be used on desktops and laptops, including systems outside the installer requirements. It runs with ordinary user permissions.

```sh
/usr/bin/python3 diagnose.py --connector dp --screen dark
```

Select `edp` for a laptop panel or `hdmi` for HDMI. Select `--screen working` when you saw the display come back. The default log window is two hours. Use `--last boot` for the current boot. If you report a problem, include the machine or motherboard model, BIOS version and the command output. A failed NVRM resume points to GPU recovery. A successful resume with a failed NVRMFB modeset points to display recovery. A successful modeset with a physically dark screen calls for checking the output link.

Support for a new eDP MUX profile requires an ACPI S3 trace showing that the panel route changes across wake and a verified restore through that board's firmware interface.

## Requirements

- Lenovo LOQ 15IAX9 (83GS) with RTX 4050 Laptop GPU `10de:28e1` and Lenovo subsystem `17aa:3d06`. The tested BIOS is `NECN53WW`.
- Internal eDP panel routed to NVIDIA in discrete-only graphics mode.
- Firmware and OpenCore configuration that can already enter **ACPI S3**. A prior macOS log with `ACPI S3 WAKE` also counts if the panel went black. Windows dual-boot users can check whether `powercfg /a` lists Standby (S3) as available. [Microsoft powercfg documentation](https://learn.microsoft.com/en-us/windows-hardware/design/device-experiences/powercfg-command-line-options#option_available_sleep_states)
- Intel macOS Tahoe with the matched HighDelay `v3.0.2-nvk` driver already working. The installer checks the installed kext UUIDs. [Base driver](https://github.com/HighDelay/nvidia-macos-driver-nvk/releases/tag/v3.0.2-nvk)
- Python 3.9 or newer and administrator access. The commands below use macOS's `/usr/bin/python3` when the Apple Command Line Tools or Xcode are installed.

The hardware test used macOS 26.7.1 (25G241) and OpenCore 1.0.9. The release is scoped to the profile above. Systems that only support S0 low-power idle need a different sleep path.

## Install

1. Download the kit and `SHA256SUMS` from the same release. In Terminal, run the following from the download directory.

   ```sh
   shasum -a 256 -c SHA256SUMS
   ditto -x -k S3-eDP-Wake-Fix-0.1.1.zip .
   cd S3-eDP-Wake-Fix-0.1.1
   /usr/bin/python3 install.py check
   sudo /usr/bin/python3 install.py install
   ```

   Keep the backup directory printed by the installer. It contains the original kexts and AuxKC. The installer compares the complete linked AuxKC against the previous one before committing the update.

2. Back up the OpenCore `EFI/OC/config.plist` used by this macOS boot. Under `NVRAM → Add → 7C436110-AB2A-4BBB-A880-FE41995C9F82 → boot-args`, append `nvrmloqs3=1` to the existing string. Include `boot-args` under `NVRAM → Delete` for the same GUID so OpenCore can apply the updated string. For an S3 boot, disable any custom ACPI table added specifically to enable macOS Deep Idle. Validate the plist with the `ocvalidate` version matched to your OpenCore.

3. Restart once. Save your work, enter Sleep, and wake with the power button or lid. Check the physical internal panel and the log below.

   ```sh
   kmutil showloaded --list-only | grep 'com.nullmoth.NVRM '
   log show --last 15m --style compact --predicate 'process == "kernel" AND (eventMessage CONTAINS "ACPI S3 WAKE" OR eventMessage CONTAINS "LOQ S3 eDP")'
   ```

The patched NVRM UUID is `1DEF6CBC-7D29-3AF7-BE5A-0881EC5316F9`. When the firmware changes the saved MUX route, the log records `discrete route restore: 0x0, route 2`. A platform that retains route 2 can wake without a restore message.

## Tested behavior

- With the external USB keyboard and mouse disconnected, the test stayed in S3 for about **75 seconds** and woke on the RTC alarm. The internal eDP link recovered at 1920 × 1080 and 144 Hz.
- With both USB peripherals connected, the machine still reported an early `XDCI CNVW` DarkWake. The internal screen recovered on full wake and was confirmed visually. Premature USB wake remains open.

If the screen stays dark, include the model, BIOS version, macOS build, base driver tag, both kext UUIDs and the relevant S3 log lines when reporting it.

## Roll back

Run the rollback subcommand with the backup directory printed by your install. The example path below is a placeholder.

```sh
sudo /usr/bin/python3 install.py rollback '/Library/NullMoth/LOQ-S3-eDP-REPLACE-ME'
```

Restore your backed-up OpenCore plist or remove `nvrmloqs3=1` from your boot arguments, then restart. The rollback matches the original macOS build and the installed AuxKC before restoring the backup.

## Source and credits

The source patch and build script use the exact HighDelay and NVIDIA commits recorded in [kit.json](kit.json). [Build instructions](scripts/BUILD.md)

Anh Tài (xnpty) tested the LOQ fix and maintains this release. NullMoth Systems wrote the macOS NVIDIA driver, HighDelay maintains the NVK fork used here, and NVIDIA provides the Open GPU Kernel Modules. The derivative is distributed under the upstream PolyForm Noncommercial license. [License](LICENSE) · [Upstream notices](NOTICE) · [NVIDIA notices](licenses/NVIDIA-open-gpu-kernel-modules-COPYING.txt)
