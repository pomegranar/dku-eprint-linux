"""Pharos Uniprint "Popup" client protocol, reimplemented for Linux.

Reverse engineered from the macOS Pharos Popup Client 9.0.10 (Popup-6212)
shipped in DKU's MACePrint.dmg.  See docs/PROTOCOL.md for the wire formats.

Two independent pieces live here:

  PopupServerClient  -- the PSPOPUP TCP protocol (port 28203).  Used to ask the
                        print server which questions a queue wants answered.
  build_popup_block  -- the opaque blob that gets prepended to the print data
                        on the LPD stream (port 515).

Nothing in here needs the Pharos GUI: the popup block is obfuscated with a key
that is hard coded in the vendor client, not with a negotiated session key.
"""

from __future__ import annotations

import os
import socket

# --- PSPOPUP packet protocol -------------------------------------------------

SIGNATURE = b"PSPOPUP"
CLIENT_VERSION = b"1003"
SEP = b"\x0c"  # form feed separates fields, both in requests and responses
HEADER_LEN = len(SIGNATURE) + len(CLIENT_VERSION) + 1 + 6 + 1  # == 19
DEFAULT_POPUP_PORT = 28203
DEFAULT_LPD_PORT = 515

# Descriptor response fields, in packet order (index 0 is the echoed verb).
DESCRIPTOR_FIELDS = [
    "name",
    "prompt",
    "description",
    "type",
    "length",
    "max",
    "min",
    "mandatory",
    "default",
    "list_entries",
    "flags",
    "hierarchy_level",
]


class PopupError(Exception):
    pass


class PopupServerClient:
    """Speaks the PSPOPUP protocol to a Pharos popup server."""

    def __init__(self, host, port=DEFAULT_POPUP_PORT, timeout=10.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock = None
        self.server_version = CLIENT_VERSION

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc):
        self.close()

    def connect(self):
        self.sock = socket.create_connection((self.host, self.port), self.timeout)
        self.sock.settimeout(self.timeout)

    def close(self):
        if self.sock is not None:
            try:
                self.sock.close()
            finally:
                self.sock = None

    # -- framing --

    @staticmethod
    def encode(fields, version=CLIENT_VERSION):
        body = b"".join(f.encode("utf-8", "replace") + SEP for f in fields)
        total = HEADER_LEN + len(body)
        return SIGNATURE + version + SEP + b"%06d" % total + SEP + body

    def _recv_exactly(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise PopupError("connection closed after %d of %d bytes" % (len(buf), n))
            buf += chunk
        return buf

    def request(self, fields):
        if self.sock is None:
            raise PopupError("not connected")
        self.sock.sendall(self.encode(fields, self.server_version))
        header = self._recv_exactly(HEADER_LEN)
        if not header.startswith(SIGNATURE):
            raise PopupError("bad packet signature: %r" % header[:7])
        parts = header.split(SEP)
        version = header[len(SIGNATURE):len(SIGNATURE) + 4]
        if int(version) < int(CLIENT_VERSION):
            raise PopupError("server version %r below minimum %r" % (version, CLIENT_VERSION))
        self.server_version = version
        try:
            total = int(parts[1])
        except (IndexError, ValueError):
            raise PopupError("bad packet header: %r" % header)
        if total < HEADER_LEN:
            raise PopupError("bad packet length: %d" % total)
        body = self._recv_exactly(total - HEADER_LEN)
        fields = body.split(SEP)
        if fields and fields[-1] == b"":
            fields.pop()
        return [f.decode("utf-8", "replace") for f in fields]

    # -- verbs --

    def init_new_job(self, hostname, device_name, queue, username, jobname):
        r = self.request(["INITNEWJOB", hostname, device_name, queue, username, jobname])
        if len(r) < 2:
            raise PopupError("short INITNEWJOB response: %r" % (r,))
        if r[1] == "NOQUEUE":
            raise PopupError("print server has no queue named %r" % queue)
        return {
            "transaction": r[1],
            "allows_last_answers": r[2] if len(r) > 2 else "0",
            "netbios_name": r[3] if len(r) > 3 else "",
            "config_flags": r[5] if len(r) > 5 else "0",
        }

    def descriptors(self, transaction):
        """Yield the queue's questions, in order, until the server runs out."""
        out = []
        while True:
            r = self.request(["GETNEXTDESCRIPTOR", str(transaction)])
            if len(r) < len(DESCRIPTOR_FIELDS) + 1:
                break  # bare verb == no more descriptors
            d = dict(zip(DESCRIPTOR_FIELDS, r[1:]))
            d["answer"] = ""
            out.append(d)
        return out

    def public_key(self):
        r = self.request(["GETPUBLICKEY"])
        if len(r) < 3:
            raise PopupError("short GETPUBLICKEY response")
        return r[1], r[2]  # modulus hex, exponent hex


def query_queue(host, queue, username, jobname="Print Job", hostname=None,
                device_name=None, port=DEFAULT_POPUP_PORT, timeout=10.0):
    """Convenience: return the descriptor list for one queue."""
    hostname = hostname or socket.gethostname()
    device_name = device_name or resolve_device_name(host)
    with PopupServerClient(host, port, timeout) as c:
        job = c.init_new_job(hostname, device_name, queue, username, jobname)
        return job, c.descriptors(job["transaction"])


def resolve_device_name(host):
    """The vendor client sends the print server's dotted-quad IP as 'device name'."""
    try:
        return socket.gethostbyname(host)
    except OSError:
        return host


# --- "Not RSA" key wrapping --------------------------------------------------
# Textbook modular exponentiation, no PKCS#1 padding, with a single 0x01 byte
# prepended when the payload would otherwise start with 0x00 or 0x01.
# Only needed if you want to negotiate a session key; the popup block itself
# does not use one.

def not_rsa_pad(data: bytes) -> bytes:
    if data[:1] in (b"\x00", b"\x01"):
        return b"\x01" + data
    return data


def not_rsa_encrypt(data: bytes, modulus_hex: str, exponent_hex: str) -> str:
    m = int.from_bytes(not_rsa_pad(data), "big")
    n = int(modulus_hex, 16)
    e = int(exponent_hex, 16)
    return "%X" % pow(m, e, n)


# --- RC4 ---------------------------------------------------------------------
# The popup block is obfuscated with this fixed key, lifted verbatim from the
# vendor client's __TEXT segment.  It is not a secret and not a session key --
# every Pharos client and server shares it.

POPUP_RC4_KEY = bytes.fromhex("4295f2a7680511b4c37439e1d2665794")


def rc4(key: bytes, data: bytes) -> bytes:
    s = list(range(256))
    j = 0
    klen = len(key)
    for i in range(256):
        j = (j + key[i % klen] + s[i]) & 0xFF
        s[i], s[j] = s[j], s[i]
    out = bytearray(len(data))
    i = j = 0
    for n, byte in enumerate(data):
        i = (i + 1) & 0xFF
        j = (j + s[i]) & 0xFF
        s[i], s[j] = s[j], s[i]
        out[n] = byte ^ s[(s[i] + s[j]) & 0xFF]
    return bytes(out)


# --- popup block -------------------------------------------------------------

BLOCK_MAGIC = bytes.fromhex("c0c1c2c3c4c5c6c7")
BLOCK_VERSION = b"154\x00"


def _cstr(value) -> bytes:
    """ASCII, lossy, NUL terminated -- matches -dataUsingEncoding: + setLength:+1."""
    return str(value).encode("ascii", "replace") + b"\x00"


def job_data_block(hostname, username, jobname, sides_imaged=0) -> bytes:
    """Section 1: who is printing what, from where."""
    return (_cstr(hostname) + _cstr(username) + _cstr(jobname)
            + _cstr(int(sides_imaged)))


def answer_block(descriptors) -> bytes:
    """Sections 2 and 3: the answers to the queue's questions.

    Descriptors whose type is Guest and whose answer is empty are skipped, as
    the vendor client does.  A descriptor carrying a hierarchy level encodes as
    a static cost-centre record instead of a plain name/answer pair.
    """
    out = bytearray()
    for d in descriptors:
        if d.get("type") == "Guest" and not d.get("answer"):
            continue
        name = d.get("name")
        if name is None:
            out += b"\x00"
        else:
            hierarchy = d.get("hierarchy_level") or ""
            if hierarchy:
                out += b"CC_Static" + b"\x00" + hierarchy.encode("ascii", "replace") + b"\r"
            else:
                out += name.encode("ascii", "replace") + b"\x00"
        answer = d.get("answer")
        if answer:
            out += answer.encode("ascii", "replace")
        out += b"\x00"
    return bytes(out)


def xml_properties_block(application="Unknown", sides_imaged=0, copies=1) -> bytes:
    """Section 4: Pharos AppTracker accounting metadata.  No trailing NUL."""
    text = ("<AppTrackerJob>\n<ProcessExecutable>"
            + str(application)
            + "</ProcessExecutable>\n<AppTrackerPages>"
            + str(int(sides_imaged))
            + "</AppTrackerPages>\n<AppTrackerCopies>"
            + str(int(copies))
            + "</AppTrackerCopies>\n</AppTrackerJob>")
    return text.encode("ascii", "replace")


def signature_block(total_len, section23_len, section4_len) -> bytes:
    """The fixed 32 byte header that precedes the obfuscated body."""
    return (BLOCK_MAGIC
            + b"%07d" % total_len + b"\x00"
            + BLOCK_VERSION
            + b"%05d" % section23_len + b"\x00"
            + b"%05d" % section4_len + b"\x00")


def build_popup_block(hostname, username, jobname, descriptors,
                      application="Unknown", sides_imaged=0, copies=1,
                      notify_block=b"") -> bytes:
    """Build the blob that goes in front of the print data on the LPD stream.

    notify_block is empty on Linux: the vendor client only fills it in when a
    Pharos Notify daemon is running locally to receive job status popups.
    """
    section1 = job_data_block(hostname, username, jobname, sides_imaged)
    section23 = answer_block(descriptors)
    section4 = xml_properties_block(application, sides_imaged, copies)

    body = section1 + section23 + notify_block + section4
    # The vendor client lumps sections 1-3 and the notify block together here.
    prefix_len = len(section1) + len(section23) + len(notify_block)

    return (signature_block(len(body), prefix_len, len(section4))
            + rc4(POPUP_RC4_KEY, body))


# --- LPD (RFC 1179) ----------------------------------------------------------

def _lpd_command(sock, data):
    sock.sendall(data)
    ack = sock.recv(1)
    if ack != b"\x00":
        raise PopupError("LPD server refused command (ack=%r)" % ack)


def lpd_send(host, queue, username, jobname, payload, port=DEFAULT_LPD_PORT,
             timeout=60.0, hostname=None, job_id=1, source_port=True):
    """Send one job to an LPD queue.

    RFC 1179 wants the client to use a source port in 721-731.  That needs
    privileges; CUPS backends run privileged, so we try and fall back quietly.
    """
    hostname = (hostname or socket.gethostname())[:31]
    username = username[:31]
    job_id = int(job_id) % 1000

    sock = _lpd_connect(host, port, timeout, source_port)
    try:
        _lpd_command(sock, b"\x02" + queue.encode("ascii", "replace") + b"\n")

        control = "".join([
            "H%s\n" % hostname,
            "P%s\n" % username,
            "J%s\n" % jobname,
            "ldfA%03d%s\n" % (job_id, hostname),
            "UdfA%03d%s\n" % (job_id, hostname),
            "N%s\n" % jobname,
        ]).encode("ascii", "replace")
        cname = "cfA%03d%s" % (job_id, hostname)
        dname = "dfA%03d%s" % (job_id, hostname)

        _lpd_command(sock, b"\x02%d %s\n" % (len(control), cname.encode()))
        sock.sendall(control + b"\x00")
        if sock.recv(1) != b"\x00":
            raise PopupError("LPD server rejected the control file")

        _lpd_command(sock, b"\x03%d %s\n" % (len(payload), dname.encode()))
        sock.sendall(payload)
        sock.sendall(b"\x00")
        if sock.recv(1) != b"\x00":
            raise PopupError("LPD server rejected the data file")
    finally:
        sock.close()


def _lpd_connect(host, port, timeout, source_port):
    addr = (host, port)
    # Only root can bind 721-731, and DKU's server is happy with an ephemeral
    # port anyway, so don't waste eleven failed binds when we aren't root.
    if source_port and hasattr(os, "geteuid") and os.geteuid() == 0:
        for lport in range(731, 720, -1):
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                sock.bind(("", lport))
                sock.settimeout(timeout)
                sock.connect(addr)
                return sock
            except OSError:
                sock.close()
    sock = socket.create_connection(addr, timeout)
    sock.settimeout(timeout)
    return sock
