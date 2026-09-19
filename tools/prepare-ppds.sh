#!/bin/bash
# Make the vendor PPDs usable on Linux.
#
#   prepare-ppds.sh SRC_DIR DEST_DIR
#
# The Ricoh PPDs ship with macOS-only absolute paths baked in.  The important
# one is:
#
#   *cupsFilter: "application/vnd.cups-postscript 0 \
#                 /Library/Printers/RICOH/Filters/pstopsRV1.app/..."
#
# On Linux that file does not exist, and cupsd does not treat it as optional:
#
#   Unable to start filter ".../pstopsRV1" - No such file or directory.
#   Stopping job because the scheduler could not execute a filter.
#
# Every job to such a queue stops dead.  Removing the line lets CUPS fall back
# to its own pstops, which is correct for what is a plain PostScript printer.
# Ricoh-specific PPD extras that the vendor filter would have applied are lost;
# ordinary printing, duplex, paper size and the popup accounting block are not.
#
# *cupsICCProfile is also stripped: the profile file is likewise absent and
# CUPS logs a warning for it on every job.
#
# Lines are commented out with '*%' rather than deleted, so the installed PPD
# still records what the vendor shipped.

set -euo pipefail

SRC="${1:?usage: prepare-ppds.sh SRC_DIR DEST_DIR}"
DEST="${2:?usage: prepare-ppds.sh SRC_DIR DEST_DIR}"

mkdir -p "$DEST"

shopt -s nullglob
ppds=("$SRC"/*.ppd)
shopt -u nullglob
if [[ ${#ppds[@]} -eq 0 ]]; then
    echo "prepare-ppds: no .ppd files in $SRC" >&2
    exit 1
fi

for src in "${ppds[@]}"; do
    name="$(basename "$src")"
    sed -E \
        -e 's|^(\*cupsFilter2?:.*/Library/.*)$|*% disabled for Linux (macOS-only filter): \1|' \
        -e 's|^(\*cupsICCProfile[^:]*:.*/Library/.*)$|*% disabled for Linux (macOS-only profile): \1|' \
        "$src" > "$DEST/$name"
    chmod 644 "$DEST/$name"

    if grep -qaE '^\*cupsFilter2?:.*/Library/' "$DEST/$name"; then
        echo "prepare-ppds: failed to neutralise $name" >&2
        exit 1
    fi
    echo "  $name"
done
