# Third-party material and provenance

## PPD files (`vendor/ppd/`)

| File | Copyright |
|---|---|
| `RICOH Aficio MP 5002.ppd` | © 2011-2013 Ricoh Company, Ltd. |
| `RICOH Aficio MP C4503.ppd` | © Ricoh Company, Ltd. |
| `MS810.ppd` | © Lexmark International, Inc. |

These are unmodified PostScript Printer Description files, extracted from the
`MACePrint.dmg` installer distributed by Duke Kunshan University. They are
included so the driver works out of the box.

They are **not** covered by this project's MIT license and are not the
project author's to relicense. They are redistributed for interoperability
under their respective vendors' terms. PPDs are conventionally distributed
with printer drivers for exactly this purpose, but if you are repackaging this
project — for a distribution, or commercially — review those terms yourself.

If you would rather not redistribute them, delete `vendor/ppd/` and point
`install.sh` at PPDs you obtain yourself:

```sh
sudo ./install.sh --ppd-dir /path/to/your/ppds
```

Equivalent PPDs also ship with many Linux distributions via `foomatic-db` and
OpenPrinting, and Ricoh and Lexmark publish them for direct download.

## Protocol documentation (`docs/PROTOCOL.md`)

The Pharos Uniprint popup protocol is not publicly specified. The format
documented here was recovered by analysing the macOS Pharos Popup Client
(version 9.0.10, `Popup-6212`) from the same installer, and confirmed against a
live print server.

No vendor code is copied or redistributed in this repository. The
documentation describes wire formats — facts about how bytes are arranged on a
network connection — which are not themselves copyrightable, and the
implementation in `src/` was written from that documentation.

Reverse engineering for the purpose of achieving interoperability is expressly
permitted in many jurisdictions (for example EU Directive 2009/24/EC Art. 6,
and in the United States under the reasoning of *Sega v. Accolade* and
*Sony v. Connectix*). Your jurisdiction may differ.

## Trademarks

Pharos and Uniprint are trademarks of Pharos Systems International. Ricoh and
Aficio are trademarks of Ricoh Company, Ltd. Lexmark is a trademark of Lexmark
International, Inc. Duke and Duke Kunshan are trademarks of Duke University.
Used here descriptively, to identify the systems this software interoperates
with.
