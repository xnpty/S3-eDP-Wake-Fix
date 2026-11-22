#!/usr/bin/env python3
"""Exercise the installer transaction with an isolated set of kext paths."""

from contextlib import redirect_stdout
from importlib.util import module_from_spec, spec_from_file_location
from io import StringIO
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch


location = Path(__file__).resolve().parents[1] / "install.py"
spec = spec_from_file_location("loq_installer", location)
installer = module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name).resolve()
        self.names = list(installer.KEXTS)
        self.ext = root / "Extensions"
        self.aux = root / "AuxKC"
        self.backups = root / "Backups"
        self.backups.mkdir()
        self.aux.write_bytes(b"existing")
        self.before = {"com.apple.nke.rvi": ("2.1.0", "/Library/Apple/RVI.kext", "RVI")}
        for name in self.names:
            for directory, value in ((self.ext, b"stock"), (root / "payload", b"patched")):
                file = installer.executable(directory, name)
                file.parent.mkdir(parents=True)
                file.write_bytes(value)
            kext = installer.KEXTS[name]
            self.before[f"com.nullmoth.{name}"] = (
                kext["version"], str(installer.bundle(self.ext, name)), kext["stock_uuid"]
            )

        self.after = dict(self.before)
        for name in self.names:
            kext = installer.KEXTS[name]
            self.after[f"com.nullmoth.{name}"] = (
                kext["version"], str(installer.bundle(self.ext, name)), kext["uuid"]
            )

        methods = patch.multiple(
            installer, AUXKC=self.aux, EXTENSIONS=self.ext, BACKUPS=self.backups, HERE=root,
            preflight=lambda: (self.before, self.names),
            verify_payload=lambda directory, name: None,
            copy_bundle=shutil.copytree,
            build_auxkc=lambda out, before: out.write_bytes(b"linked"),
            inventory=lambda out: self.after,
            macos_build=lambda: "25G241",
        )
        methods.start()
        self.addCleanup(methods.stop)

    def test_install_replaces_the_matched_pair(self):
        with redirect_stdout(StringIO()):
            installer.install()
        self.assertEqual(self.aux.read_bytes(), b"linked")
        [backup] = self.backups.iterdir()
        self.assertEqual((backup / self.aux.name).read_bytes(), b"existing")
        for name in self.names:
            self.assertEqual(installer.executable(self.ext, name).read_bytes(), b"patched")
            self.assertEqual(installer.executable(backup / "original", name).read_bytes(), b"stock")
        self.assertTrue((backup / "receipt.json").is_file())

    def test_a_dropped_auxkc_dependency_rolls_back_both_kexts(self):
        self.after.pop("com.apple.nke.rvi")
        with redirect_stdout(StringIO()), self.assertRaisesRegex(RuntimeError, "com.apple.nke.rvi"):
            installer.install()
        self.assertEqual(self.aux.read_bytes(), b"existing")
        for name in self.names:
            self.assertEqual(installer.executable(self.ext, name).read_bytes(), b"stock")

    def test_failure_replacing_the_second_bundle_restores_the_first(self):
        work = installer.work_directory()
        shutil.copytree(installer.bundle(installer.HERE / "payload", self.names[0]),
                        installer.bundle(work / "stage", self.names[0]))
        with self.assertRaises(FileNotFoundError), installer.replace_bundles(work, self.names):
            self.fail("Both bundles must exist before the transaction finishes")
        for name in self.names:
            self.assertEqual(installer.executable(self.ext, name).read_bytes(), b"stock")

    def test_already_patched_is_a_no_op(self):
        self.names.clear()
        with redirect_stdout(StringIO()):
            installer.install()
        self.assertEqual(self.aux.read_bytes(), b"existing")
        self.assertEqual(list(self.backups.iterdir()), [])

    def test_explicit_rollback_restores_the_stock_pair_and_collection(self):
        with redirect_stdout(StringIO()):
            installer.install()
        [backup] = self.backups.iterdir()
        original_stat = Path.stat

        def root_owned_backup(path, *args, **kwargs):
            stats = original_stat(path, *args, **kwargs)
            if path == backup:
                fields = list(stats)
                fields[4] = 0  # st_uid
                return os.stat_result(fields)
            return stats

        with patch.object(Path, "stat", root_owned_backup), redirect_stdout(StringIO()):
            installer.rollback(backup)
        self.assertEqual(self.aux.read_bytes(), b"existing")
        for name in self.names:
            self.assertEqual(installer.executable(self.ext, name).read_bytes(), b"stock")


if __name__ == "__main__":
    unittest.main()
