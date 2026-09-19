"""Tests for the `dku-eprint print` subcommand.

The command is a wrapper over lp(1), so what matters is the argv it builds;
subprocess.run is stubbed out rather than actually spooling anything.
"""

import argparse
import contextlib
import importlib.machinery
import importlib.util
import io
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "src")
sys.path.insert(0, SRC)

# The CLI has no .py extension, so it needs an explicit source loader.
_loader = importlib.machinery.SourceFileLoader("dku_eprint_cli", os.path.join(SRC, "dku-eprint"))
spec = importlib.util.spec_from_loader("dku_eprint_cli", _loader)
cli = importlib.util.module_from_spec(spec)
_loader.exec_module(cli)


class FakeProc:
    def __init__(self, returncode=0):
        self.returncode = returncode


class TestPrintCommand(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self._real_run = cli.subprocess.run
        cli.subprocess.run = lambda cmd, *a, **kw: (self.calls.append(cmd), FakeProc())[1]

        # load_config() resolves its search path at import time, so stub it
        # rather than trying to point it at a temporary file.
        self.config = {"server": "127.0.0.1", "netid": "testnetid", "users": {}}
        self._real_load = cli.load_config
        cli.load_config = lambda *a, **kw: self.config

        fh = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        fh.write(b"%PDF-1.4\n")
        fh.close()
        self.pdf = fh.name

    def tearDown(self):
        cli.subprocess.run = self._real_run
        cli.load_config = self._real_load
        os.unlink(self.pdf)

    def _parse(self, argv):
        old = sys.argv
        sys.argv = ["dku-eprint"] + argv
        try:
            with contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()):
                return cli.main()
        finally:
            sys.argv = old

    def test_default_queue_and_file(self):
        self.assertEqual(self._parse(["print", self.pdf]), 0)
        self.assertEqual(self.calls[0],
                         ["lp", "-d", "ePrint-Ricoh-BW", "--", self.pdf])

    def test_options_are_translated(self):
        self._parse(["print", "--queue", "ePrint-Ricoh-Color", "-n", "3",
                     "--sides", "two-sided-long-edge", "--pages", "1-4",
                     "--media", "A4", "-t", "essay", "-o", "fit-to-page",
                     self.pdf])
        self.assertEqual(self.calls[0], [
            "lp", "-d", "ePrint-Ricoh-Color", "-t", "essay", "-n", "3",
            "-o", "sides=two-sided-long-edge", "-o", "page-ranges=1-4",
            "-o", "media=A4", "-o", "fit-to-page", "--", self.pdf,
        ])

    def test_netid_override_travels_as_a_job_option(self):
        self._parse(["--netid", "xyz789", "print", self.pdf])
        self.assertIn("dku-netid=xyz789", self.calls[0])

    def test_netid_works_after_the_subcommand_too(self):
        """The subparser's SUPPRESS default must not clobber the global one."""
        self._parse(["print", "--netid", "xyz789", self.pdf])
        self.assertIn("dku-netid=xyz789", self.calls[0])

    def test_netid_is_optional(self):
        self._parse(["print", self.pdf])
        self.assertFalse([a for a in self.calls[0] if a.startswith("dku-netid=")])

    def test_stdin_when_no_files(self):
        self._parse(["print"])
        self.assertEqual(self.calls[0][-1], "-")

    def test_unknown_queue_is_rejected(self):
        with self.assertRaises(SystemExit) as caught:
            self._parse(["print", "--queue", "nope", self.pdf])
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(self.calls, [])

    def test_unknown_queue_is_rejected_by_the_command_too(self):
        """argparse catches it first, but cmd_print does not trust that."""
        args = argparse.Namespace(queue="nope", files=[self.pdf], netid=None,
                                  copies=None, title=None, sides=None,
                                  pages=None, media=None, option=None)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.cmd_print(args), 1)
        self.assertEqual(self.calls, [])

    def test_missing_file_is_rejected(self):
        self.assertEqual(self._parse(["print", "/nonexistent/file.pdf"]), 1)
        self.assertEqual(self.calls, [])

    def test_missing_netid_is_rejected(self):
        self.config["netid"] = ""
        self.assertEqual(self._parse(["print", self.pdf]), 1)
        self.assertEqual(self.calls, [])

    def test_missing_netid_is_allowed_when_prompting(self):
        self.config["netid"] = ""
        self.config["prompt"] = "always"
        self.assertEqual(self._parse(["print", self.pdf]), 0)
        self.assertEqual(len(self.calls), 1)


class TestTopLevelHelp(unittest.TestCase):
    """The help is generated from the parser; check the ordering we impose."""

    def setUp(self):
        # A wide terminal keeps argparse from hyphenating the values we look for.
        self._old_columns = os.environ.get("COLUMNS")
        os.environ["COLUMNS"] = "200"
        self.help = self._render(["dku-eprint", "--help"])

    def tearDown(self):
        if self._old_columns is None:
            os.environ.pop("COLUMNS", None)
        else:
            os.environ["COLUMNS"] = self._old_columns

    def _render(self, argv):
        out = io.StringIO()
        old, sys.argv = sys.argv, argv
        try:
            with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
                cli.main()
        finally:
            sys.argv = old
        return out.getvalue()

    def test_every_print_option_appears(self):
        for flag in ("FILE", "--queue", "--copies", "--sides", "--media",
                     "--pages", "--title", "--netid", "--option"):
            self.assertIn(flag, self.help)

    def test_queues_and_sides_appear(self):
        for value in cli.QUEUES + cli.SIDES:
            self.assertIn(value, self.help)

    def test_management_commands_come_last(self):
        printing = self.help.index("printing options")
        management = self.help.index("setup and diagnostics")
        self.assertLess(printing, management)
        for command in ("show", "set-netid", "set-prompt", "add-queues",
                        "remove-queues", "probe", "test-page"):
            self.assertGreater(self.help.index(command), printing)

    def test_examples_come_before_the_options(self):
        self.assertLess(self.help.index("dku-eprint print report.pdf"),
                        self.help.index("printing options"))

    def test_print_is_not_listed_as_a_management_command(self):
        management = self.help[self.help.index("setup and diagnostics"):]
        self.assertNotIn("\n  print ", management)

    def test_subcommand_help_is_not_the_top_level_help(self):
        out = self._render(["dku-eprint", "print", "--help"])
        self.assertIn("usage: dku-eprint print", out)
        self.assertNotIn("setup and diagnostics", out)


if __name__ == "__main__":
    unittest.main()
