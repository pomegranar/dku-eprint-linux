#!/bin/bash
# Install dku-eprint on macOS.  No sudo: everything goes under your home.
#
#   ./install.sh [--netid abc123] [--prompt always]
#
# macOS has its own Pharos client, and SIP stops anything else being added to
# CUPS' backend directory, so there is no backend here: `dku-eprint print`
# filters with cupsfilter and sends the job to the server itself.
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SHARE="$HOME/.local/share/dku-eprint"
BIN="$HOME/.local/bin"
CONF="$HOME/.config/dku-eprint/eprint.conf"
NETID=""
PROMPT=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --netid)  NETID="$2"; shift 2 ;;
        --prompt) PROMPT="$2"; shift 2 ;;
        --server|--ppd-dir) shift 2 ;;
        --no-queues|--no-deps) shift ;;
        -h|--help) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 1 ;;
    esac
done

if [[ $EUID -eq 0 ]]; then
    echo "error: run without sudo; this installs into your home directory" >&2
    exit 1
fi
if [[ -n "$NETID" && ! "$NETID" =~ ^[A-Za-z0-9._-]{1,64}$ ]]; then
    echo "error: '$NETID' does not look like a NetID" >&2
    exit 1
fi
if [[ -z "$NETID" && -z "$PROMPT" && -t 0 ]]; then
    read -r -p "DKU NetID (blank to be asked on every print): " NETID
fi
[[ -z "$PROMPT" ]] && { [[ -n "$NETID" ]] && PROMPT=never || PROMPT=always; }

printf '\033[1m==>\033[0m installing to %s\n' "$SHARE"
install -d -m 755 "$SHARE" "$BIN" "$(dirname "$CONF")"
install -m 755 "$SRC_DIR/src/dku-eprint" "$SHARE/dku-eprint"
install -m 644 "$SRC_DIR/src/eprint_pharos.py" "$SRC_DIR/src/eprint_config.py" "$SHARE/"
"$SRC_DIR/tools/prepare-ppds.sh" "$SRC_DIR/vendor/ppd" "$SHARE/ppd" >/dev/null
ln -sf "$SHARE/dku-eprint" "$BIN/dku-eprint"

if [[ ! -f "$CONF" ]]; then
    cat > "$CONF" <<CONFEOF
# DKU ePrint configuration
server = dku-ep-ps2-pap1.oit.duke.edu
netid = $NETID

# never  = always use the netid above
# always = ask in a dialog for every job
prompt = $PROMPT
CONFEOF
    echo "    wrote $CONF"
fi

case ":$PATH:" in
    *":$BIN:"*) ;;
    *) echo "    add $BIN to your PATH" ;;
esac
echo "    check: dku-eprint probe"
