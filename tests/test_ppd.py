"""The vendor PPDs must be made Linux-safe before CUPS sees them.

The Ricoh PPDs carry:

    *cupsFilter: "application/vnd.cups-postscript 0 /Library/Printers/RICOH/..."

cupsd does not treat a missing cupsFilter as optional. Left in place it logs

    Unable to start filter ".../pstopsRV1" - No such file or directory.
    Stopping job because the scheduler could not execute a filter.

and every job to that queue stops dead, which is invisible to any test that
talks LPD directly instead of going through CUPS.
"""

import os
import re
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
VENDOR = os.path.join(ROOT, "vendor", "ppd")
PREPARE = os.path.join(ROOT, "tools", "prepare-ppds.sh")

BAD_FILTER = re.compile(rb"^\*cupsFilter2?:.*/Library/", re.M)
BAD_PROFILE = re.compile(rb"^\*cupsICCProfile[^:]*:.*/Library/", re.M)


class TestVendorPPDsAreUnmodified(unittest.TestCase):
    """vendor/ppd must stay pristine; THIRD-PARTY.md says so."""

    def test_vendor_ricoh_still_has_the_macos_filter(self):
        path = os.path.join(VENDOR, "RICOH Aficio MP 5002.ppd")
        with open(path, "rb") as fh:
            self.assertRegex(fh.read(), BAD_FILTER)


class TestPrepared(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dest = tempfile.mkdtemp()
        proc = subprocess.run([PREPARE, VENDOR, cls.dest],
                              capture_output=True, timeout=60)
        if proc.returncode != 0:
            raise AssertionError(proc.stderr.decode())

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dest, ignore_errors=True)

    def _read(self, name):
        with open(os.path.join(self.dest, name), "rb") as fh:
            return fh.read()

    def test_all_ppds_are_copied(self):
        self.assertEqual(
            sorted(os.listdir(self.dest)),
            sorted(os.listdir(VENDOR)))

    def test_no_macos_filter_survives(self):
        for name in os.listdir(self.dest):
            self.assertNotRegex(self._read(name), BAD_FILTER, name)

    def test_no_macos_icc_profile_survives(self):
        for name in os.listdir(self.dest):
            self.assertNotRegex(self._read(name), BAD_PROFILE, name)

    def test_disabled_lines_are_kept_as_comments(self):
        # Commented out rather than deleted, so provenance is still visible.
        data = self._read("RICOH Aficio MP 5002.ppd")
        self.assertIn(b"*% disabled for Linux (macOS-only filter):", data)
        self.assertIn(b"pstopsRV1", data)

    def test_ppd_is_still_structurally_valid(self):
        data = self._read("RICOH Aficio MP 5002.ppd")
        self.assertTrue(data.startswith(b"*PPD-Adobe"))
        for required in (b"*ModelName:", b"*NickName:", b"*PageSize"):
            self.assertIn(required, data)

    def test_lexmark_ppd_is_untouched(self):
        # MS810 has no cupsFilter, so it should come through byte for byte.
        with open(os.path.join(VENDOR, "MS810.ppd"), "rb") as fh:
            original = fh.read()
        self.assertEqual(self._read("MS810.ppd"), original)

    @unittest.skipUnless(shutil.which("cupstestppd"), "cupstestppd not installed")
    def test_cupstestppd_accepts_the_result(self):
        for name in os.listdir(self.dest):
            proc = subprocess.run(
                ["cupstestppd", "-W", "all", os.path.join(self.dest, name)],
                capture_output=True, timeout=60)
            self.assertEqual(proc.returncode, 0,
                             "%s: %s" % (name, proc.stdout.decode()[:400]))


class TestPrepareScriptErrors(unittest.TestCase):
    def test_empty_source_dir_fails_loudly(self):
        src = tempfile.mkdtemp()
        dest = tempfile.mkdtemp()
        try:
            proc = subprocess.run([PREPARE, src, dest],
                                  capture_output=True, timeout=60)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn(b"no .ppd files", proc.stderr)
        finally:
            shutil.rmtree(src, ignore_errors=True)
            shutil.rmtree(dest, ignore_errors=True)

    def test_missing_arguments_fail(self):
        proc = subprocess.run([PREPARE], capture_output=True, timeout=60)
        self.assertNotEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
