#!/usr/bin/env python3
"""Install or roll back the matched LOQ NVRM and NVRMFB kexts."""

import argparse
from contextlib import contextmanager
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import plistlib
import shutil
import struct
import subprocess
import sys
import tempfile
from uuid import UUID


HERE = Path(__file__).resolve().parent
KIT = json.loads((HERE / "kit.json").read_text())
NAME = KIT["name"]
KEXTS = KIT["kexts"]
EXTENSIONS = Path("/Library/Extensions")
AUXKC = Path("/Library/KernelCollections/AuxiliaryKernelExtensions.kc")
BASE_KC = Path("/System/Library/KernelCollections")
BACKUPS = Path("/Library/NullMoth")
PREFIX = "LOQ-S3-eDP-"
GPU_PATH = "IOACPIPlane:/_SB/PC00/PEG1@10000/PEGP@0"


def run(*args):
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        output = (result.stderr + result.stdout).decode(errors="replace").strip()
        raise RuntimeError(f"{Path(args[0]).name} failed\n{output}")
    return result.stdout


def digest(file):
    with file.open("rb") as stream:
        result = sha256()
        for data in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(data)
        return result.hexdigest()


def bundle(directory, name):
    return directory / f"{name}.kext"


def executable(directory, name):
    return bundle(directory, name) / "Contents" / "MacOS" / name


def info_plist(directory, name):
    return bundle(directory, name) / "Contents" / "Info.plist"


def binary_uuid(file):
    with file.open("rb") as stream:
        header = stream.read(32)
        if header[:8] != bytes.fromhex("cffaedfe07000001"):
            raise RuntimeError(f"Expected an x86_64 Mach-O executable at {file}")
        count, length = struct.unpack_from("<II", header, 16)
        if length > 1024 * 1024 or count > length // 8:
            raise RuntimeError(f"Invalid Mach-O header at {file}")
        commands = stream.read(length)
    offset = 0
    for _ in range(count):
        command, size = struct.unpack_from("<II", commands, offset)
        if size < 8 or offset + size > len(commands):
            break
        if command == 0x1B and size == 24:
            return str(UUID(bytes=commands[offset + 8:offset + 24])).upper()
        offset += size
    raise RuntimeError(f"Missing Mach-O UUID at {file}")


def inventory(file):
    entries = {}
    output = run("/usr/bin/kmutil", "inspect", "-V", "release", "--no-header",
                 "--show-kext-uuids", "-A", str(file)).decode()
    for line in output.splitlines():
        if line.count("\t") < 3:
            continue
        identifier, version, location, uuid = line.split("\t", 3)
        if identifier in entries:
            raise RuntimeError(f"Duplicate AuxKC bundle {identifier}")
        entries[identifier] = (version, location, uuid.strip().strip("()").upper())
    if not entries:
        raise RuntimeError(f"No bundles found in {file}")
    return entries


def preflight():
    if os.uname().machine != "x86_64" or os.uname().release.split(".")[0] != "25":
        raise RuntimeError("This kit requires Intel macOS Tahoe.")
    nodes = plistlib.loads(run("/usr/sbin/ioreg", "-a", "-r", "-n", "PEGP", "-d", "1"))
    pci = {"vendor-id": "de100000", "device-id": "e1280000",
           "subsystem-vendor-id": "aa170000", "subsystem-id": "063d0000"}
    if not any(node.get("acpi-path") == GPU_PATH and
               all(node.get(key) == bytes.fromhex(value) for key, value in pci.items())
               for node in nodes):
        raise RuntimeError("The Lenovo PEG1 RTX 4050 Laptop GPU profile was not found.")
    entries = inventory(AUXKC)
    for identifier, (version, uuid) in KIT["companions"].items():
        actual = entries.get(identifier)
        if not actual or (actual[0], actual[2]) != (version, uuid):
            raise RuntimeError(f"Install the matching HighDelay v3.0.2-nvk base driver first ({identifier}).")
    changes = []
    for name, spec in KEXTS.items():
        target = bundle(EXTENSIONS, name)
        identifier = f"com.nullmoth.{name}"
        entry = entries.get(identifier)
        if target.is_symlink() or not entry or entry[:2] != (spec["version"], str(target)):
            raise RuntimeError(f"Expected the {spec['version']} release of {name} in /Library/Extensions.")
        if digest(info_plist(EXTENSIONS, name)) != spec["plist_sha256"]:
            raise RuntimeError(f"The installed {name} bundle metadata differs from the supported release.")
        uuid = binary_uuid(executable(EXTENSIONS, name))
        if uuid != entry[2] or uuid not in (spec["stock_uuid"], spec["uuid"]):
            raise RuntimeError(f"{name} differs from the supported stock or patched build.")
        if uuid == spec["stock_uuid"]:
            changes.append(name)
        elif digest(executable(EXTENSIONS, name)) != spec["binary_sha256"]:
            raise RuntimeError(f"The patched {name} executable has a different digest.")
    return entries, changes


def verify_payload(directory, name):
    spec = KEXTS[name]
    if (digest(executable(directory, name)) != spec["binary_sha256"] or
            digest(info_plist(directory, name)) != spec["plist_sha256"] or
            binary_uuid(executable(directory, name)) != spec["uuid"]):
        raise RuntimeError(f"Release payload checksum mismatch for {name}.")
    run("/usr/bin/codesign", "--verify", "--strict", str(bundle(directory, name)))


def copy_bundle(source, target):
    run("/usr/bin/ditto", "--noqtn", str(source), str(target))
    run("/usr/sbin/chown", "-R", "root:wheel", str(target))
    run("/bin/chmod", "-R", "go-w", str(target))


@contextmanager
def install_lock():
    if os.geteuid() != 0:
        raise RuntimeError("Run install or rollback through sudo.")
    BACKUPS.mkdir(exist_ok=True)
    if BACKUPS.is_symlink() or BACKUPS.stat().st_uid != 0:
        raise RuntimeError(f"Expected a root-owned backup directory at {BACKUPS}")
    fd = os.open(BACKUPS / ".loq-s3-edp.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "r+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def work_directory():
    work = Path(tempfile.mkdtemp(prefix=PREFIX, dir=BACKUPS))
    (work / "original").mkdir()
    (work / "stage").mkdir()
    return work


@contextmanager
def replace_bundles(work, names):
    moved = []
    try:
        for name in names:
            target = bundle(EXTENSIONS, name)
            original = bundle(work / "original", name)
            staged = bundle(work / "stage", name)
            target.rename(original)
            moved.append((target, original, staged))
            staged.rename(target)
        yield
    except BaseException:
        for target, original, staged in reversed(moved):
            if target.exists():
                target.rename(staged)
            original.rename(target)
        raise


def build_auxkc(out, entries):
    args = [
        "/usr/bin/kmutil", "create", "-V", "release", "-a", "x86_64", "--new", "aux",
        "-B", str(BASE_KC / "BootKernelExtensions.kc"),
        "-S", str(BASE_KC / "SystemKernelExtensions.kc"), "-A", str(out),
        "--no-authorization",
    ]
    for _, installed, _ in sorted(entries.values()):
        if not Path(installed).is_dir():
            raise RuntimeError(f"Existing AuxKC bundle is missing at {installed}")
        args.extend(["--bundle-path", installed])
    run(*args)


def macos_build():
    return run("/usr/bin/sw_vers", "-buildVersion").decode().strip()


def install():
    before, names = preflight()
    if not names:
        print("Both release kexts are already installed.")
        return
    work = work_directory()
    print(f"Backup directory {work}", flush=True)
    old_aux = work / AUXKC.name
    shutil.copy2(AUXKC, old_aux)
    original_digests = {name: digest(executable(EXTENSIONS, name)) for name in names}
    for name in names:
        verify_payload(HERE / "payload", name)
        copy_bundle(bundle(HERE / "payload", name), bundle(work / "stage", name))
        verify_payload(work / "stage", name)

    out = work / "linked.kc"
    with replace_bundles(work, names):
        build_auxkc(out, before)
        expected = dict(before)
        for name in names:
            spec = KEXTS[name]
            expected[f"com.nullmoth.{name}"] = (spec["version"], str(bundle(EXTENSIONS, name)), spec["uuid"])
        after = inventory(out)
        if after != expected:
            changed = sorted(key for key in after.keys() | expected.keys() if after.get(key) != expected.get(key))
            raise RuntimeError(f"The linked AuxKC changed unexpected entries: {', '.join(changed)}")
        old_hash = digest(old_aux)
        if digest(AUXKC) != old_hash:
            raise RuntimeError("The system AuxKC changed during the install.")
        out.chmod(AUXKC.stat().st_mode & 0o777)
        receipt = {"macos_build": macos_build(), "previous_aux": old_hash,
                   "installed_aux": digest(out), "original_digests": original_digests}
        (work / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        out.replace(AUXKC)
    print(f"Installed {NAME}. Apply the OpenCore boot argument and restart once.")
    print(f"Rollback with sudo /usr/bin/python3 install.py rollback '{work}'")


def rollback(backup):
    backup = backup.resolve()
    if backup.parent != BACKUPS.resolve() or not backup.name.startswith(PREFIX) or backup.stat().st_uid != 0:
        raise RuntimeError("Pass the backup directory printed by this installer.")
    receipt = json.loads((backup / "receipt.json").read_text())
    if receipt["macos_build"] != macos_build() or receipt["installed_aux"] != digest(AUXKC):
        raise RuntimeError("The macOS build or AuxKC has changed since installation.")
    old_aux = backup / AUXKC.name
    if digest(old_aux) != receipt["previous_aux"]:
        raise RuntimeError("The original AuxKC backup differs from its recorded checksum.")
    originals = receipt["original_digests"]
    if not originals or set(originals) - KEXTS.keys():
        raise RuntimeError("Unexpected kexts in the rollback receipt.")
    work = work_directory()
    for name, expected in originals.items():
        verify_payload(EXTENSIONS, name)
        if digest(executable(backup / "original", name)) != expected:
            raise RuntimeError(f"The {name} backup differs from its recorded checksum.")
        copy_bundle(bundle(backup / "original", name), bundle(work / "stage", name))
    out = work / "restored.kc"
    shutil.copy2(old_aux, out)
    with replace_bundles(work, originals):
        if digest(AUXKC) != receipt["installed_aux"]:
            raise RuntimeError("The system AuxKC changed during rollback.")
        out.replace(AUXKC)
    print("Restored the original kexts and AuxKC. Restore your EFI backup or remove nvrmloqs3=1, then restart.")


def main():
    parser = argparse.ArgumentParser(description=f"{NAME}. {__doc__}")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check")
    commands.add_parser("install")
    undo = commands.add_parser("rollback")
    undo.add_argument("backup", type=Path)
    args = parser.parse_args()
    if args.command == "check":
        _, changes = preflight()
        print("Supported LOQ RTX 4050 profile and matching Tahoe driver found.")
        print(f"Kexts to update: {', '.join(changes) or 'both already patched'}")
        return
    with install_lock():
        if args.command == "install":
            install()
        else:
            rollback(args.backup)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, KeyError, struct.error) as error:
        raise SystemExit(f"{NAME}: {error}") from None
