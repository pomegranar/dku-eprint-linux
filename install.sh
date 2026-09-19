#!/bin/bash
# Install the DKU ePrint driver for Linux/CUPS.
#
#   sudo ./install.sh                       interactive: asks for NetID + mode
#   sudo ./install.sh --netid abc123         store a NetID, no prompting
#   sudo ./install.sh --prompt always        ask in a dialog for every job
#   sudo ./install.sh --no-queues            install files only
#   sudo ./install.sh --ppd-dir DIR          use PPDs from elsewhere
#   sudo ./install.sh --server HOST          non-default print server
#   sudo ./install.sh --no-deps              don't try to install packages
#
# Works on Debian/Ubuntu, Fedora/RHEL and Arch.  See THIRD-PARTY.md for the
# PPD licensing note.

set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SHARE_DIR=/usr/share/dku-eprint
PPD_DIR=/usr/share/ppd/dku-eprint
CONF_DIR=/etc/dku-eprint
BIN_DIR=/usr/local/bin
UNIT_DIR=/usr/lib/systemd/user

SERVER=dku-ep-ps2-pap1.oit.duke.edu
NETID=""
PROMPT=""
MAKE_QUEUES=1
INSTALL_DEPS=1
SRC_PPD_DIR="$SRC_DIR/vendor/ppd"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --netid)     NETID="$2"; shift 2 ;;
        --prompt)    PROMPT="$2"; shift 2 ;;
        --server)    SERVER="$2"; shift 2 ;;
        --ppd-dir)   SRC_PPD_DIR="$2"; shift 2 ;;
        --no-queues) MAKE_QUEUES=0; shift ;;
        --no-deps)   INSTALL_DEPS=0; shift ;;
        -h|--help)   sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 1 ;;
    esac
done

if [[ $EUID -ne 0 ]]; then
    echo "error: run me with sudo" >&2
    exit 1
fi

say()  { printf '\033[1m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[33mwarning:\033[0m %s\n' "$*" >&2; }

# --- dependencies -----------------------------------------------------------

detect_distro() {
    if [[ -r /etc/os-release ]]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        echo "${ID_LIKE:-$ID}"
    else
        echo unknown
    fi
}

install_deps() {
    local family missing=()
    family="$(detect_distro)"

    command -v cupsd   >/dev/null || command -v cups-config >/dev/null || missing+=(cups)
    command -v python3 >/dev/null || missing+=(python3)
    # Only needed for the dialog; harmless to add regardless.
    command -v zenity  >/dev/null || command -v kdialog >/dev/null || missing+=(zenity)

    if [[ ${#missing[@]} -eq 0 ]]; then
        say "Dependencies already present"
        return 0
    fi
    if [[ $INSTALL_DEPS -eq 0 ]]; then
        warn "missing: ${missing[*]} (--no-deps given, not installing)"
        return 0
    fi

    say "Installing: ${missing[*]}"
    case "$family" in
        *debian*|*ubuntu*)
            apt-get update -qq
            apt-get install -y "${missing[@]}"
            ;;
        *fedora*|*rhel*|*centos*)
            dnf install -y "${missing[@]}"
            ;;
        *arch*)
            # Arch calls it 'python', not 'python3'.
            local pac=("${missing[@]/#python3/python}")
            pacman -Sy --needed --noconfirm "${pac[@]}"
            ;;
        *)
            warn "unrecognised distribution; install these yourself: ${missing[*]}"
            ;;
    esac
}

install_deps

BACKEND_DIR=""
for candidate in /usr/lib/cups/backend /usr/lib64/cups/backend \
                 /usr/libexec/cups/backend; do
    [[ -d "$candidate" ]] && { BACKEND_DIR="$candidate"; break; }
done
[[ -z "$BACKEND_DIR" ]] && { echo "error: CUPS backend directory not found" >&2; exit 1; }
command -v lpadmin >/dev/null || { echo "error: lpadmin not found" >&2; exit 1; }

# --- interactive setup ------------------------------------------------------
# Only when nothing was given on the command line and we have a terminal.

if [[ -z "$NETID" && -z "$PROMPT" && -t 0 ]]; then
    echo
    echo "How should your DKU NetID be supplied?"
    echo "  1) Store it now, use it for every job   (recommended)"
    echo "  2) Ask me in a dialog box for each job"
    read -r -p "Choice [1]: " choice
    case "${choice:-1}" in
        2) PROMPT=always ;;
        *) PROMPT=never ;;
    esac
    read -r -p "DKU NetID (blank to set later): " NETID
    echo
fi
PROMPT="${PROMPT:-never}"

if [[ -n "$NETID" && ! "$NETID" =~ ^[A-Za-z0-9._-]{1,64}$ ]]; then
    echo "error: '$NETID' does not look like a NetID" >&2
    exit 1
fi

# --- files ------------------------------------------------------------------

say "Installing support files to $SHARE_DIR"
install -d -m 755 "$SHARE_DIR" "$PPD_DIR" "$CONF_DIR"
install -m 644 "$SRC_DIR/src/eprint_pharos.py" "$SHARE_DIR/"
install -m 644 "$SRC_DIR/src/eprint_config.py" "$SHARE_DIR/"

# The vendor Ricoh PPDs name a macOS-only filter; left in place, cupsd stops
# every job to those queues.  prepare-ppds.sh neutralises that.
say "Installing PPDs from $SRC_PPD_DIR"
if ! "$SRC_DIR/tools/prepare-ppds.sh" "$SRC_PPD_DIR" "$PPD_DIR"; then
    echo "       supply your own with --ppd-dir DIR (see THIRD-PARTY.md)" >&2
    exit 1
fi

# CUPS refuses to run a backend that is group- or world-writable, and runs it as
# root only when it is not world-readable either.
say "Installing backend to $BACKEND_DIR/popup"
install -m 700 -o root -g root "$SRC_DIR/src/popup" "$BACKEND_DIR/popup"

say "Installing commands to $BIN_DIR"
install -d -m 755 "$BIN_DIR"
install -m 755 "$SRC_DIR/src/dku-eprint"       "$BIN_DIR/dku-eprint"
install -m 755 "$SRC_DIR/src/dku-eprint-agent" "$BIN_DIR/dku-eprint-agent"

if [[ -d /usr/lib/systemd ]]; then
    install -d -m 755 "$UNIT_DIR"
    install -m 644 "$SRC_DIR/packaging/systemd/dku-eprint-agent.service" "$UNIT_DIR/"
fi

# --- configuration ----------------------------------------------------------

if [[ -f "$CONF_DIR/eprint.conf" ]]; then
    say "Keeping existing $CONF_DIR/eprint.conf"
    [[ -n "$NETID" ]] && "$BIN_DIR/dku-eprint" set-netid "$NETID"
else
    cat > "$CONF_DIR/eprint.conf" <<EOF
# DKU ePrint configuration
# Jobs are held at the server and released with your DKUCard.

server = $SERVER
netid = ${NETID}

# never  = always use the netid above
# always = ask in a desktop dialog for every job (needs dku-eprint-agent)
prompt = $PROMPT
EOF
    chmod 644 "$CONF_DIR/eprint.conf"
    say "Wrote $CONF_DIR/eprint.conf"
fi

# --- queues -----------------------------------------------------------------

if [[ $MAKE_QUEUES -eq 1 ]]; then
    say "Creating print queues"
    add_queue() {
        local name="$1" ppd="$2" queue="$3"
        if [[ ! -f "$PPD_DIR/$ppd" ]]; then
            warn "no PPD '$ppd', skipping queue $name"
            return 0
        fi
        lpadmin -x "$name" 2>/dev/null || true
        lpadmin -p "$name" -D "$name" -E \
                -P "$PPD_DIR/$ppd" \
                -o printer-is-shared=false \
                -o PageSize=Letter \
                -v "popup://$SERVER/$queue"
        echo "    $name"
    }
    add_queue ePrint-Ricoh-BW    "RICOH Aficio MP 5002.ppd"  ePrint-Ricoh-BW
    add_queue ePrint-Ricoh-Color "RICOH Aficio MP C4503.ppd" ePrint-Ricoh-Color
    add_queue ePrint-Lexmark-BW  "MS810.ppd"                 ePrint-Lexmark-BW
fi

# --- popup agent ------------------------------------------------------------

if [[ "$PROMPT" == "always" ]]; then
    say "Enabling the popup agent for the desktop session"
    # Enable for the invoking user, not root -- it is a session service.
    real_user="${SUDO_USER:-}"
    if [[ -n "$real_user" && "$real_user" != root ]]; then
        if runuser -l "$real_user" -c \
             'systemctl --user enable --now dku-eprint-agent.service' 2>/dev/null; then
            echo "    enabled for $real_user"
        else
            warn "could not enable it automatically; as $real_user, run:"
            echo "      systemctl --user enable --now dku-eprint-agent.service"
        fi
    else
        warn "run this as your normal user to finish:"
        echo "      systemctl --user enable --now dku-eprint-agent.service"
    fi
fi

echo
say "Done."
if [[ -z "$NETID" && "$PROMPT" != "always" ]]; then
    echo "    Next: sudo dku-eprint set-netid <your-netid>"
fi
echo "    Check:  dku-eprint probe"
echo "    Test:   dku-eprint test-page"
