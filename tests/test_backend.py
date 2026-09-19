"""End-to-end test of the CUPS backend against a stub LPD server.

Drives src/popup exactly the way cupsd does and checks that what lands on the
wire is a well formed RFC 1179 conversation carrying a valid popup block.
"""

import importlib.machinery
import importlib.util
import os
import socket
import subprocess
import sys
import tempfile
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "src")
sys.path.insert(0, SRC)

import eprint_pharos as p

# The backend has no .py extension, so it needs an explicit source loader.
_loader = importlib.machinery.SourceFileLoader("popup_backend", os.path.join(SRC, "popup"))
spec = importlib.util.spec_from_loader("popup_backend", _loader)
popup_backend = importlib.util.module_from_spec(spec)
_loader.exec_module(popup_backend)


class StubLPD(threading.Thread):
    """Minimal RFC 1179 receiver: acks everything, records the data file."""

    daemon = True

    def __init__(self):
        super().__init__()
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.queue = None
        self.control = None
        self.data = None
        self.error = None

    def run(self):
        try:
            conn, _ = self.sock.accept()
            with conn:
                self.queue = self._read_line(conn)[1:]
                conn.sendall(b"\x00")
                while True:
                    line = self._read_line(conn)
                    if not line:
                        break
                    cmd, rest = line[0:1], line[1:]
                    count, _, name = rest.partition(b" ")
                    conn.sendall(b"\x00")
                    payload = self._read_exactly(conn, int(count))
                    self._read_exactly(conn, 1)  # trailing NUL
                    conn.sendall(b"\x00")
                    if cmd == b"\x02":
                        self.control = payload
                    elif cmd == b"\x03":
                        self.data = payload
                        break
        except Exception as exc:  # surfaced by the test
            self.error = exc
        finally:
            self.sock.close()

    @staticmethod
    def _read_line(conn):
        out = b""
        while not out.endswith(b"\n"):
            c = conn.recv(1)
            if not c:
                return out
            out += c
        return out[:-1]

    @staticmethod
    def _read_exactly(conn, n):
        buf = b""
        while len(buf) < n:
            c = conn.recv(n - len(buf))
            if not c:
                break
            buf += c
        return buf


class TestURIParsing(unittest.TestCase):
    def test_host_and_queue(self):
        self.assertEqual(popup_backend.parse_device_uri("popup://ps.example.edu/Q1"),
                         ("ps.example.edu", 515, "Q1"))

    def test_explicit_port(self):
        self.assertEqual(popup_backend.parse_device_uri("popup://ps.example.edu:9100/Q1"),
                         ("ps.example.edu", 9100, "Q1"))

    def test_missing_queue_is_rejected(self):
        with self.assertRaises(ValueError):
            popup_backend.parse_device_uri("popup://ps.example.edu/")

    def test_missing_scheme_is_rejected(self):
        with self.assertRaises(ValueError):
            popup_backend.parse_device_uri("ps.example.edu/Q1")


class TestOptionParsing(unittest.TestCase):
    def test_key_value_pairs(self):
        self.assertEqual(popup_backend.parse_options("a=1 b=2"), {"a": "1", "b": "2"})

    def test_bare_flag(self):
        self.assertEqual(popup_backend.parse_options("duplex"), {"duplex": ""})

    def test_empty(self):
        self.assertEqual(popup_backend.parse_options(""), {})
        self.assertEqual(popup_backend.parse_options(None), {})


class TestBackendRun(unittest.TestCase):
    def _run(self, env_extra, argv_extra, job_bytes=b"%!PS\nshowpage\n"):
        server = StubLPD()
        server.start()

        with tempfile.NamedTemporaryFile(suffix=".ps", delete=False) as fh:
            fh.write(job_bytes)
            job_path = fh.name

        conf = tempfile.NamedTemporaryFile("w", suffix=".conf", delete=False)
        conf.write("server = 127.0.0.1\nnetid = testnetid\n")
        conf.close()

        env = dict(os.environ)
        env["DEVICE_URI"] = "popup://127.0.0.1:%d/ePrint-Ricoh-BW" % server.port
        env["DKU_EPRINT_CONFIG"] = conf.name
        env.update(env_extra)

        argv = [sys.executable, os.path.join(SRC, "popup"),
                "42", "alice", "report.pdf", "1", ""] + argv_extra + [job_path]
        proc = subprocess.run(argv, env=env, capture_output=True, timeout=60)
        server.join(timeout=10)
        os.unlink(job_path)
        os.unlink(conf.name)
        return proc, server

    def test_delivers_block_and_job(self):
        proc, server = self._run({}, [])
        self.assertIsNone(server.error)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        self.assertEqual(server.queue, b"ePrint-Ricoh-BW")

        # Control file identifies the job by NetID, not the Unix account.
        self.assertIn(b"Ptestnetid\n", server.control)
        self.assertIn(b"Jreport.pdf\n", server.control)

        # Data file is [32 byte header][RC4 body][PostScript].
        data = server.data
        self.assertEqual(data[:8].hex(), "c0c1c2c3c4c5c6c7")
        block_len = int(data[8:15])
        body = p.rc4(p.POPUP_RC4_KEY, data[32:32 + block_len])

        # Section 1 is hostname\0 netid\0 jobname\0 sides\0, in that order.
        self.assertEqual(body.split(b"\x00")[:4],
                         [socket.gethostname().encode(), b"testnetid",
                          b"report.pdf", b"0"])
        self.assertTrue(body.endswith(b"</AppTrackerJob>"))
        self.assertEqual(data[32 + block_len:], b"%!PS\nshowpage\n")

    def test_answers_use_configured_netid(self):
        _, server = self._run({}, [])
        block_len = int(server.data[8:15])
        body = p.rc4(p.POPUP_RC4_KEY, server.data[32:32 + block_len])
        s23 = int(server.data[20:25])
        self.assertIn(b"Username\x00testnetid\x00", body[:s23])

    def test_missing_netid_requests_auth(self):
        conf = tempfile.NamedTemporaryFile("w", suffix=".conf", delete=False)
        conf.write("server = 127.0.0.1\nnetid =\n")
        conf.close()
        env = dict(os.environ)
        env["DEVICE_URI"] = "popup://127.0.0.1:515/ePrint-Ricoh-BW"
        env["DKU_EPRINT_CONFIG"] = conf.name
        env.pop("DKU_EPRINT_NETID", None)
        proc = subprocess.run(
            [sys.executable, os.path.join(SRC, "popup"),
             "1", "alice", "t", "1", "", "/dev/null"],
            env=env, capture_output=True, timeout=30)
        os.unlink(conf.name)
        self.assertEqual(proc.returncode, popup_backend.CUPS_BACKEND_AUTH_REQUIRED)
        self.assertIn(b"no DKU NetID configured", proc.stderr)

    def test_discovery_mode(self):
        proc = subprocess.run([sys.executable, os.path.join(SRC, "popup")],
                              capture_output=True, timeout=30)
        self.assertEqual(proc.returncode, 0)
        self.assertIn(b"network popup", proc.stdout)

    def test_wrong_argument_count_fails(self):
        proc = subprocess.run([sys.executable, os.path.join(SRC, "popup"), "1", "2"],
                              capture_output=True, timeout=30)
        self.assertEqual(proc.returncode, popup_backend.CUPS_BACKEND_FAILED)
        self.assertIn(b"expected 6 or 7 arguments", proc.stderr)


if __name__ == "__main__":
    unittest.main()


class TestTestPageRendering(unittest.TestCase):
    """The PostScript '%!' header once collided with %-formatting."""

    def setUp(self):
        loader = importlib.machinery.SourceFileLoader(
            "dku_eprint_cli", os.path.join(SRC, "dku-eprint"))
        spec = importlib.util.spec_from_loader("dku_eprint_cli", loader)
        self.cli = importlib.util.module_from_spec(spec)
        loader.exec_module(self.cli)

    def test_keeps_postscript_header(self):
        page = self.cli.render_test_page("abc123", "box", "ePrint-Ricoh-BW")
        self.assertTrue(page.startswith(b"%!PS-Adobe-3.0\n"))

    def test_substitutes_all_placeholders(self):
        page = self.cli.render_test_page("abc123", "box", "ePrint-Ricoh-BW")
        self.assertIn(b"(NetID: abc123)", page)
        self.assertIn(b"(Host: box)", page)
        self.assertIn(b"(Queue: ePrint-Ricoh-BW)", page)
        self.assertNotIn(b"@", page)

    def test_escapes_postscript_string_delimiters(self):
        page = self.cli.render_test_page("a(b)c\\d", "box", "q")
        self.assertIn(rb"(NetID: a\(b\)c\\d)", page)
