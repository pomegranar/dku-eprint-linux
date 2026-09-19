# DKU ePrint for Linux

Print to Duke Kunshan's ePrint service from Linux. DKU runs **Pharos Uniprint**,
which ships clients for macOS and Windows only; this is a clean reimplementation
of the parts Linux needs: a `popup://` CUPS backend, the three vendor PPDs, and
a `dku-eprint` command.

Jobs are held at the server and released with your DKUCard at any ePrint
station, exactly as with the macOS client.

## Install

```sh
git clone https://github.com/pomegranar/dku-eprint-linux
cd dku-eprint-linux && sudo ./install.sh
```

This installs any missing dependencies, sets up the backend and PPDs, creates
the three queues (`ePrint-Ricoh-BW`, `ePrint-Ricoh-Color`, `ePrint-Lexmark-BW`,
matching the macOS installer) and asks how you want to supply your NetID.

```sh
sudo ./install.sh --netid abc123     # non-interactive: store it, use it always
sudo ./install.sh --prompt always    # non-interactive: ask in a dialog
sudo ./uninstall.sh                  # remove it (--purge drops the config too)
```

You need CUPS and `python3` (standard library only), and a network path to
`dku-ep-ps2-pap1.oit.duke.edu` on TCP **515** and **28203**.

## Printing

```sh
dku-eprint print report.pdf                        # black & white, the default
dku-eprint print --queue ePrint-Ricoh-Color *.pdf  # colour
dku-eprint print -n 2 --sides two-sided-long-edge --pages 1-4 report.pdf
cat report.pdf | dku-eprint print                  # standard input
```

`dku-eprint print --help` lists every option: queue, copies, sides, page size,
page range, job title, and `-o` for anything else `lp(1)` accepts.

It is a wrapper over `lp`, so `lp -d ePrint-Ricoh-BW report.pdf` does the same
thing, and any application's print dialog works too. PDFs, PostScript, images
and plain text all print.

To check the setup: `dku-eprint probe` asks the server what each queue wants,
and `dku-eprint test-page` sends a real page.

## Your NetID

Every job is charged to a NetID. Either store one, or be asked for each job:

```sh
sudo dku-eprint set-netid abc123          # use it for every job
sudo dku-eprint set-prompt always         # or ask in a desktop dialog instead
systemctl --user enable --now dku-eprint-agent.service   # needed by 'always'
dku-eprint show                           # what is in effect now
```

Storing one is simplest, and the only option that works headless or over SSH.
The dialog reproduces the macOS client, and is what the distro packages default
to. A CUPS backend cannot open a window itself, so `dku-eprint-agent` runs in
your desktop session and shows the dialog with `zenity` or `kdialog`; if it is
not running, the backend falls back to the stored NetID rather than failing the
job. Cancelling the dialog cancels the print.

Settings live in `/etc/dku-eprint/eprint.conf`, which also takes per-account
overrides for shared machines:

```ini
server = dku-ep-ps2-pap1.oit.duke.edu
netid  = abc123
prompt = never          # or 'always' for the dialog

[users]
bob = xyz789
```

## If the printer looks dead

The print server is on campus RFC 1918 space. A VPN that captures the default
route (a Tailscale exit node, WireGuard with `AllowedIPs = 0.0.0.0/0`) sends
campus traffic off site. Check which interface it resolves through:

```sh
ip route get "$(getent hosts dku-ep-ps2-pap1.oit.duke.edu | awk '{print $1}')"
# want 'dev <your LAN interface>', not 'dev tailscale0' / 'dev wg0'
```

If it points at the tunnel, exempt the campus range rather than disconnecting.
Tailscale's own rules sit at priorities 5210-5270, so a lower number wins:

```sh
sudo ip rule add to 10.0.0.0/8 lookup main priority 5206
```

This is runtime only, and is lost on reboot or VPN restart; persist it with a
NetworkManager dispatcher script or a systemd unit. Tailscale's
`--exit-node-allow-lan-access` is usually not enough on its own, as it covers
your immediate subnet only.

If the queues are missing entirely, `cupsd` was probably not running at install
time: `sudo dku-eprint add-queues`.

## How it works

The DKU queues are ordinary LPD queues that expect a Pharos "popup block" in
front of the print data, carrying the username and the answers to whatever the
queue asks. For DKU that is always one question: *"Please enter your DKU
NetID"*. A service on port 28203 exists so clients can discover the questions.

The wire format, and how it was recovered from the vendor binary, is in
[`docs/PROTOCOL.md`](docs/PROTOCOL.md). Run the tests with `python3 -m unittest
discover -s tests`; they need no network.

## Packaging

```sh
make rpm     # Fedora/RHEL   -> build/rpm/RPMS/noarch/
make deb     # Debian/Ubuntu -> ../dku-eprint_1.0.0*.deb
make arch    # Arch          -> build/arch/
```

Installing a package creates the queues and enables the NetID dialog, so there
is nothing to do at a terminal afterwards. Only the RPM has been built and
inspected: the Debian and Arch recipes are written to spec but have never been
run. The driver itself has printed for real from both Fedora and Arch.

## License

The original work (`src/`, `tests/`, `docs/`, the install scripts) is MIT
licensed; see [`LICENSE`](LICENSE). The PPDs in `vendor/ppd/` are Ricoh's and
Lexmark's, redistributed unmodified for interoperability and **not** covered by
it — see [`THIRD-PARTY.md`](THIRD-PARTY.md).

Not affiliated with or endorsed by Pharos Systems International, Ricoh, Lexmark,
Duke University, or Duke Kunshan University.

Two limits worth knowing: only the plaintext LPD path is implemented (the vendor
client can also wrap the stream in AES, with plaintext as its documented
fallback), and the cost-centre and guest-account question types are encoded per
the vendor format but untested, as DKU's queues do not use them.
