#!/bin/bash
# Remove the DKU ePrint driver.  Keeps /etc/dku-eprint unless --purge is given.
set -euo pipefail

PURGE=0
[[ "${1:-}" == "--purge" ]] && PURGE=1

if [[ $EUID -ne 0 ]]; then
    echo "error: run me with sudo" >&2
    exit 1
fi

say() { printf '\033[1m==>\033[0m %s\n' "$*"; }

# Stop the per-user agent before removing its binary.
real_user="${SUDO_USER:-}"
if [[ -n "$real_user" && "$real_user" != root ]]; then
    runuser -l "$real_user" -c \
        'systemctl --user disable --now dku-eprint-agent.service' \
        >/dev/null 2>&1 && say "Stopped the popup agent for $real_user" || true
fi

say "Removing print queues"
for name in ePrint-Ricoh-BW ePrint-Ricoh-Color ePrint-Lexmark-BW \
            DKU-Ricoh-BW DKU-ePrint-color DKU-ePrint-BW; do
    if lpstat -p "$name" >/dev/null 2>&1; then
        lpadmin -x "$name" && echo "    $name"
    fi
done

say "Removing files"
for dir in /usr/lib/cups/backend /usr/lib64/cups/backend /usr/libexec/cups/backend; do
    [[ -f "$dir/popup" ]] && { rm -f "$dir/popup"; echo "    $dir/popup"; }
done

rm -f /usr/local/bin/dku-eprint /usr/local/bin/dku-eprint-agent
rm -f /usr/lib/systemd/user/dku-eprint-agent.service
rm -rf /usr/share/dku-eprint /usr/share/ppd/dku-eprint
echo "    support files, commands and unit"

if [[ $PURGE -eq 1 ]]; then
    rm -rf /etc/dku-eprint
    say "Removed /etc/dku-eprint"
else
    say "Kept /etc/dku-eprint (use --purge to remove)"
fi

echo
echo "Done. If you installed from a package instead, use your package manager."
