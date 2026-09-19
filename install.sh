#!/bin/bash
# Install the DKU ePrint driver for Linux/CUPS.
#
#   sudo ./install.sh [--netid abc123] [--server host] [--no-queues]
#                     [--ppd-dir DIR]
#
# Installs the 'popup' CUPS backend, the vendor PPDs, and the three ePrint
# queues that the macOS installer creates.
#
# --ppd-dir sources the PPDs from somewhere other than vendor/ppd, for people
# who would rather supply their own copies. See THIRD-PARTY.md.

set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SHARE_DIR=/usr/share/dku-eprint
PPD_DIR=/usr/share/ppd/dku-eprint
CONF_DIR=/etc/dku-eprint
BIN_DIR=/usr/local/bin
SERVER=dku-ep-ps2-pap1.oit.duke.edu
NETID=""
MAKE_QUEUES=1
SRC_PPD_DIR="$SRC_DIR/vendor/ppd"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --netid)     NETID="$2"; shift 2 ;;
        --server)    SERVER="$2"; shift 2 ;;
        --no-queues) MAKE_QUEUES=0; shift ;;
        --ppd-dir)   SRC_PPD_DIR="$2"; shift 2 ;;
        -h|--help)   sed -n '2,14p' "$0"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 1 ;;
    esac
done

if [[ $EUID -ne 0 ]]; then
    echo "error: run me with sudo" >&2
    exit 1
fi

BACKEND_DIR=""
for candidate in /usr/lib/cups/backend /usr/lib64/cups/backend /usr/libexec/cups/backend; do
    [[ -d "$candidate" ]] && { BACKEND_DIR="$candidate"; break; }
done
if [[ -z "$BACKEND_DIR" ]]; then
    echo "error: could not find the CUPS backend directory; is CUPS installed?" >&2
    exit 1
fi

command -v lpadmin >/dev/null || { echo "error: lpadmin not found" >&2; exit 1; }
command -v python3 >/dev/null || { echo "error: python3 not found" >&2; exit 1; }

echo "Installing support files to $SHARE_DIR"
install -d -m 755 "$SHARE_DIR" "$PPD_DIR" "$CONF_DIR"
install -m 644 "$SRC_DIR/src/eprint_pharos.py" "$SHARE_DIR/"
install -m 644 "$SRC_DIR/src/eprint_config.py" "$SHARE_DIR/"

echo "Installing PPDs from $SRC_PPD_DIR to $PPD_DIR"
shopt -s nullglob
ppds=("$SRC_PPD_DIR"/*.ppd)
shopt -u nullglob
if [[ ${#ppds[@]} -eq 0 ]]; then
    echo "error: no .ppd files in $SRC_PPD_DIR" >&2
    echo "       supply your own with --ppd-dir DIR (see THIRD-PARTY.md)" >&2
    exit 1
fi
install -m 644 "${ppds[@]}" "$PPD_DIR/"

# CUPS refuses to run a backend that is group- or world-writable, and only runs
# it as root when it is not world-readable either.  Root is what lets us bind
# the privileged LPD source port that RFC 1179 asks for.
echo "Installing backend to $BACKEND_DIR/popup"
install -m 700 -o root -g root "$SRC_DIR/src/popup" "$BACKEND_DIR/popup"

echo "Installing dku-eprint to $BIN_DIR"
install -d -m 755 "$BIN_DIR"
install -m 755 "$SRC_DIR/src/dku-eprint" "$BIN_DIR/dku-eprint"

if [[ ! -f "$CONF_DIR/eprint.conf" ]]; then
    cat > "$CONF_DIR/eprint.conf" <<EOF
# DKU ePrint configuration
# Set 'netid' to your DKU NetID; jobs are released with your DKUCard.

server = $SERVER
netid = ${NETID}
EOF
    chmod 644 "$CONF_DIR/eprint.conf"
    echo "Wrote $CONF_DIR/eprint.conf"
elif [[ -n "$NETID" ]]; then
    "$BIN_DIR/dku-eprint" set-netid "$NETID"
fi

if [[ $MAKE_QUEUES -eq 1 ]]; then
    echo "Creating print queues"
    add_queue() {
        local name="$1" ppd="$2" queue="$3"
        lpadmin -x "$name" 2>/dev/null || true
        lpadmin -p "$name" -D "$name" -E \
                -P "$PPD_DIR/$ppd" \
                -o printer-is-shared=false \
                -o PageSize=Letter \
                -v "popup://$SERVER/$queue"
        echo "  $name -> popup://$SERVER/$queue"
    }
    add_queue ePrint-Ricoh-BW    "RICOH Aficio MP 5002.ppd"  ePrint-Ricoh-BW
    add_queue ePrint-Ricoh-Color "RICOH Aficio MP C4503.ppd" ePrint-Ricoh-Color
    add_queue ePrint-Lexmark-BW  "MS810.ppd"                 ePrint-Lexmark-BW
fi

echo
echo "Done."
if [[ -z "$NETID" ]] && ! grep -qE '^netid\s*=\s*\S' "$CONF_DIR/eprint.conf"; then
    echo "Next: sudo dku-eprint set-netid <your-netid>"
fi
echo "Check it with:  dku-eprint probe"
echo "Test it with:   dku-eprint test-page"
