"""Tests for the popup-agent path.

The agent itself shells out to zenity/kdialog, so here we stub the dialog and
exercise everything around it: the socket protocol, NetID validation, and the
backend's fallback behaviour when the agent is missing, cancels, or answers.
"""

import importlib.machinery
import importlib.util
import json
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

from eprint_config import valid_netid


def _load(name, filename):
    loader = importlib.machinery.SourceFileLoader(name, os.path.join(SRC, filename))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


popup_backend = _load("popup_backend_agent", "popup")


class StubAgent(threading.Thread):
    """Stands in for dku-eprint-agent on a socket of our choosing."""

    daemon = True

    def __init__(self, reply):
        super().__init__()
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "dku-eprint.sock")
        self.reply = reply
        self.request = None
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(self.path)
        self.sock.listen(1)

    def run(self):
        try:
            conn, _ = self.sock.accept()
            with conn:
                data = b""
                while not data.endswith(b"\n"):
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                self.request = json.loads(data.decode())
                conn.sendall((json.dumps(self.reply) + "\n").encode())
        except Exception:
            pass
        finally:
            self.sock.close()

    def cleanup(self):
        for path in (self.path, self.dir):
            try:
                os.unlink(path) if path == self.path else os.rmdir(path)
            except OSError:
                pass


class TestNetIDValidation(unittest.TestCase):
    def test_accepts_ordinary_netids(self):
        for good in ("abc123", "xyz789", "a.b-c_d", "x" * 64):
            self.assertTrue(valid_netid(good), good)

    def test_rejects_empty_and_overlong(self):
        self.assertFalse(valid_netid(""))
        self.assertFalse(valid_netid("x" * 65))

    def test_rejects_lpd_control_file_injection(self):
        # A newline would forge extra control-file lines on the LPD stream.
        self.assertFalse(valid_netid("abc\nPevil"))
        self.assertFalse(valid_netid("abc\r\nPevil"))

    def test_rejects_shell_and_path_characters(self):
        for bad in ("a b", "a;b", "../etc/passwd", "a$b", "a|b"):
            self.assertFalse(valid_netid(bad), bad)


class TestAgentProtocol(unittest.TestCase):
    def _ask(self, reply):
        agent = StubAgent(reply)
        agent.start()
        try:
            # Call through the real function with the socket path patched in.
            orig = popup_backend.agent_socket_path
            popup_backend.agent_socket_path = lambda user: agent.path
            try:
                got = popup_backend.ask_agent("someone", "ePrint-Ricoh-BW",
                                              "Please enter your DKU NetID", "abc123")
            finally:
                popup_backend.agent_socket_path = orig
            agent.join(timeout=5)
            return got, agent
        finally:
            pass

    def test_returns_netid(self):
        got, agent = self._ask({"netid": "xyz789"})
        self.assertEqual(got, {"netid": "xyz789"})
        agent.cleanup()

    def test_request_carries_queue_and_default(self):
        _, agent = self._ask({"netid": "xyz789"})
        self.assertEqual(agent.request["op"], "ask")
        self.assertEqual(agent.request["queue"], "ePrint-Ricoh-BW")
        self.assertEqual(agent.request["default"], "abc123")
        agent.cleanup()

    def test_cancellation_is_reported(self):
        got, agent = self._ask({"error": "cancelled"})
        self.assertEqual(got.get("error"), "cancelled")
        agent.cleanup()

    def test_missing_socket_returns_none(self):
        orig = popup_backend.agent_socket_path
        popup_backend.agent_socket_path = lambda user: "/nonexistent/dku.sock"
        try:
            self.assertIsNone(
                popup_backend.ask_agent("someone", "q", "prompt", ""))
        finally:
            popup_backend.agent_socket_path = orig

    def test_unknown_user_returns_none(self):
        self.assertIsNone(
            popup_backend.agent_socket_path("no-such-user-here-12345"))


class TestBackendPromptModes(unittest.TestCase):
    """Drive the real backend with prompt=always and no agent present."""

    def _run_backend(self, conf_text, user="root"):
        conf = tempfile.NamedTemporaryFile("w", suffix=".conf", delete=False)
        conf.write(conf_text)
        conf.close()
        env = dict(os.environ)
        env["DEVICE_URI"] = "popup://127.0.0.1:1/ePrint-Ricoh-BW"
        env["DKU_EPRINT_CONFIG"] = conf.name
        env.pop("DKU_EPRINT_NETID", None)
        proc = subprocess.run(
            [sys.executable, os.path.join(SRC, "popup"),
             "1", user, "t", "1", "", "/dev/null"],
            env=env, capture_output=True, timeout=60)
        os.unlink(conf.name)
        return proc

    def test_prompt_always_falls_back_to_stored_netid(self):
        # No agent socket exists for this user, so the stored value is used.
        proc = self._run_backend(
            "server = 127.0.0.1\nnetid = stored1\nprompt = always\n")
        self.assertIn(b"popup agent unavailable", proc.stderr)
        # /dev/null is empty, so it stops at the empty-job check, not on NetID.
        self.assertNotIn(b"no DKU NetID configured", proc.stderr)

    def test_prompt_always_without_stored_netid_asks_for_auth(self):
        proc = self._run_backend(
            "server = 127.0.0.1\nnetid =\nprompt = always\n")
        self.assertEqual(proc.returncode, popup_backend.CUPS_BACKEND_AUTH_REQUIRED)

    def test_malformed_stored_netid_is_refused(self):
        proc = self._run_backend(
            "server = 127.0.0.1\nnetid = bad id here\nprompt = never\n")
        self.assertEqual(proc.returncode, popup_backend.CUPS_BACKEND_FAILED)
        self.assertIn(b"malformed NetID", proc.stderr)


if __name__ == "__main__":
    unittest.main()
