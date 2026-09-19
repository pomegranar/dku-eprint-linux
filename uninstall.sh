#!/bin/bash
# Remove the DKU ePrint driver.  Keeps /etc/dku-eprint unless --purge is given.
set -euo pipefail

PURGE=0
[[ "${1:-}" == "--purge" ]] && PURGE=1

if [[ $EUID -ne 0 ]]; then
    echo "error: run me with sudo" >&2
    exit 1
fi

for name in ePrint-Ricoh-BW ePrint-Ricoh-Color ePrint-Lexmark-BW \
            DKU-Ricoh-BW DKU-ePrint-color DKU-ePrint-BW; do
    if lpstat -p "$name" >/dev/null 2>&1; then
        lpadmin -x "$name" && echo "Removed queue $name"
    fi
done

for dir in /usr/lib/cups/backend /usr/lib64/cups/backend /usr/libexec/cups/backend; do
    if [[ -f "$dir/popup" ]]; then
        rm -f "$dir/popup"
        echo "Removed $dir/popup"
    fi
done

rm -rf /usr/share/dku-eprint /usr/share/ppd/dku-eprint
rm -f /usr/local/bin/dku-eprint
echo "Removed support files"

if [[ $PURGE -eq 1 ]]; then
    rm -rf /etc/dku-eprint
    echo "Removed /etc/dku-eprint"
else
    echo "Kept /etc/dku-eprint (use --purge to remove)"
fi
