# DKU ePrint for Linux

A Linux/CUPS driver for Duke Kunshan's ePrint service, which runs **Pharos
Uniprint**. Pharos ships clients for macOS and Windows only; this is a clean
reimplementation of the bits Linux needs.

It provides:

* a `popup://` **CUPS backend** that speaks the Pharos popup protocol and
  delivers jobs over LPD,
* the three vendor **PPDs** (Ricoh MP 5002, Ricoh MP C4503, Lexmark MS810),
  lifted unchanged from the official `MACePrint.dmg`,
* `dku-eprint`, a small CLI to configure and test it.

Jobs are held at the server and released with your DKUCard at any ePrint
station, exactly as with the macOS client.

## Install

```sh
git clone <this repo> && cd linux-eprint
sudo ./install.sh --netid your-netid
```

That installs the backend, the PPDs, and three queues — `ePrint-Ricoh-BW`,
`ePrint-Ricoh-Color` and `ePrint-Lexmark-BW` — matching what the macOS installer
creates.

Verify:

```sh
dku-eprint probe        # ask the server what each queue requires
dku-eprint test-page    # send a real test page
lp -d ePrint-Ricoh-BW file.pdf
```

Remove it with `sudo ./uninstall.sh` (add `--purge` to drop the config too).

## Requirements

* CUPS and `python3` (standard library only — no third-party packages)
* Network reach to `dku-ep-ps2-pap1.oit.duke.edu` on TCP **515** and **28203**

### VPNs and split tunnelling

The print server is on campus RFC 1918 space (`10.0.0.0/8`). If you run a VPN
that captures the default route — a Tailscale exit node, WireGuard with
`AllowedIPs = 0.0.0.0/0`, a corporate client — campus traffic gets tunnelled off
site and the printer looks dead.

The only thing that matters is that the server resolves via your LAN interface:

```sh
ip route get "$(getent hosts dku-ep-ps2-pap1.oit.duke.edu | awk '{print $1}')"
# want: 'dev <your LAN interface>', not 'dev tailscale0' / 'dev wg0'
```

If it points at the tunnel, you don't need to disconnect — just exempt the
campus range. For Tailscale, its own rules sit at priorities 5210-5270, so a
lower number wins:

```sh
sudo ip rule add to 10.0.0.0/8 lookup main priority 5206
```

Note that Tailscale's `--exit-node-allow-lan-access` alone is usually *not*
enough: it adds a `throw` route for your immediate subnet only, and the print
server generally lives on a different one.

`ip rule` changes are **runtime only** — lost on reboot and on VPN restart. To
persist, use a NetworkManager dispatcher script
(`/etc/NetworkManager/dispatcher.d/`) or a small systemd unit. If printing works
today but breaks after a reboot, check this first:

```sh
ip rule show | grep 5206
```

Dropping the exit node entirely (`tailscale set --exit-node=`) also works, and is
less disruptive than disconnecting from your tailnet.

## Configuration

`/etc/dku-eprint/eprint.conf`:

```ini
server = dku-ep-ps2-pap1.oit.duke.edu
netid  = abc123

# Optional per-account overrides for shared machines
[users]
alice = abc123
bob   = xyz789
```

```sh
sudo dku-eprint set-netid abc123
sudo dku-eprint set-netid xyz789 --user bob
dku-eprint show
```

### Why a config file instead of a popup

The macOS client shows a window asking for your NetID at print time. A CUPS
backend can't do that: it runs as the `lp` user with no session, no display, and
often before you're back at the machine. So the NetID is configured once,
up front, and every job uses it.

The backend still asks the server which questions the queue wants, so if DKU
ever adds a question the failure is a clear log line rather than a silently
malformed job.

## How it works

The DKU queues are ordinary LPD queues that expect a Pharos "popup block" in
front of the print data, carrying the username and the answers to the queue's
questions. A separate service on port 28203 exists only so clients can discover
what those questions are.

For DKU, every queue asks exactly one: *"Please enter your DKU NetID"*.

The full wire format — packet framing, the 32-byte block header, the four body
sections, and the RC4 obfuscation — is documented in
[`docs/PROTOCOL.md`](docs/PROTOCOL.md), along with how it was recovered from the
vendor binary.

## Tests

```sh
python3 -m unittest discover -s tests
```

38 tests: wire-format checks against captured bytes, RC4 against a published
vector, and a full backend run driven exactly as `cupsd` drives it against a
stub LPD server. They need no network and touch nothing outside `/tmp`.

## Layout

```
src/eprint_pharos.py   protocol library (popup protocol, block builder, LPD)
src/eprint_config.py   config file handling
src/popup              the CUPS backend
src/dku-eprint         admin/diagnostic CLI
vendor/ppd/            PPDs from MACePrint.dmg, unmodified
docs/PROTOCOL.md       wire format documentation
tests/                 unit and end-to-end tests
LICENSE                MIT, for the original work
THIRD-PARTY.md         provenance of vendor PPDs and the RE basis
```

## License

The original work here — `src/`, `tests/`, `docs/`, and the install scripts —
is MIT licensed. See [`LICENSE`](LICENSE).

The PPDs in `vendor/ppd/` are Ricoh's and Lexmark's, redistributed unmodified
for interoperability and **not** covered by that license. Provenance and the
reverse-engineering basis are set out in [`THIRD-PARTY.md`](THIRD-PARTY.md).

Not affiliated with or endorsed by Pharos Systems International, Ricoh,
Lexmark, Duke University, or Duke Kunshan University.

## Scope and caveats

* Only the plaintext LPD path is implemented. The vendor backend can also wrap
  the stream in AES after fetching a public key from the LPD server; DKU's
  server accepts plaintext, which is the vendor client's own documented
  fallback.
* Cost-centre and guest-account question types are encoded per the vendor format
  but are untested — DKU's queues don't use them.
