# Pharos Uniprint "popup" protocol

Reverse engineered from the macOS **Pharos Popup Client 9.0.10** (`Popup-6212`)
found in `MACePrint.dmg`, and verified against DKU's live print server
`dku-ep-ps2-pap1.oit.duke.edu`.

All offsets below refer to `Library/Application Support/Pharos/Popup.app/Contents/MacOS/Popup`
(x86_64 Mach-O) unless stated otherwise.

## Overview

A Pharos "popup" print queue is an ordinary **LPD** queue (RFC 1179, TCP 515)
that expects an opaque **popup block** to be prepended to the print data. The
block carries who is printing and the answers to whatever questions the queue is
configured to ask.

A second, separate service, the **popup server** on TCP 28203, exists only so
the client can discover what those questions are. The print data never goes
through it.

```
  client ──PSPOPUP/28203──► popup server      "what do you need to know?"
  client ──LPD/515────────► print server      [popup block][PostScript]
```

The macOS client also installs a `popup://` CUPS backend that rewrites the URI
to `lpd://` and hands off to the stock CUPS `lpd` backend after writing the
block. This driver does the LPD conversation itself.

## 1. PSPOPUP packet protocol (TCP 28203)

Both directions use the same framing. Fields are separated by **0x0C** (form
feed), including a trailing separator after the last field.

```
 ┌───────────┬──────────┬──────┬────────────┬──────┬─────────────────┐
 │ "PSPOPUP" │ version  │ 0x0C │ length     │ 0x0C │ field 0x0C ...  │
 │  7 bytes  │ 4 bytes  │      │ 6 digits   │      │                 │
 └───────────┴──────────┴──────┴────────────┴──────┴─────────────────┘
```

* `version`: client sends `1003`; DKU's server answers `1005`. The client
  caps the version it echoes at `1005`.
* `length`: zero-padded decimal, **including the 19-byte header**.
* Field 0 of a response echoes the request verb.

`-[PUClient packetHeaderLength]` computes `7 + 4 + 1 + 6 + 1 = 19`.

Once a session key has been set, packet *bodies* are AES-128-CBC encrypted. That
step is optional and this driver does not use it: nothing we need to ask is
sensitive, and the popup block does not use the session key either (see §3).

### Verbs

| Request | Fields | Response fields |
|---|---|---|
| `INITNEWJOB` | hostname, device name, queue, username, job name | verb, transaction, allows-last-answers, NetBIOS name, ?, config flags |
| `GETNEXTDESCRIPTOR` | transaction | verb + 12 descriptor fields, or bare verb when exhausted |
| `GETPUBLICKEY` | none | verb, modulus (hex), exponent (hex) |
| `SETSESSIONKEY` | wrapped key (hex) | verb |

`device name` is the **print server's dotted-quad IP**, not the printer's:
`-[PUArgumentParser deviceName]` resolves the host out of the `popup://` device
URI and formats it `%u.%u.%u.%u`. `queue` is the last path component of the URI.

If the queue does not exist, field 1 of the `INITNEWJOB` response is `NOQUEUE`.

### Descriptor fields

In packet order after the verb, per `-[PUJob getNextDescriptor]`:

`name, prompt, description, type, length, max, min, mandatory, default,
list_entries, flags, hierarchy_level`

DKU's three ePrint queues each return exactly one descriptor:

```
name            Username
prompt          Please enter your DKU NetID
type            String
length          64
mandatory       1
flags           8
```

## 2. Key wrapping ("NotRsa")

`+[PUNotRsa notRsaEncryptData:withModulus:exponent:]` is textbook RSA: a bare
modular exponentiation with **no PKCS#1 padding**:

1. If the payload's first byte is `0x00` or `0x01`, prepend `0x01`
   (`+[PUNotRsa paddedData:]`). This just avoids leading-zero ambiguity in
   `BN_bin2bn`.
2. `result = payload^e mod n`, sent as an uppercase hex string.

DKU's server offers a 1024-bit modulus with exponent `0x11` (17).

Only needed for `SETSESSIONKEY`, which this driver does not send.

## 3. The popup block

Built by `+[PUBlockBuilder popupBlockForDescriptors:]` at `0x10000b588`.

```
 ┌────────────────────────┬──────────────────────────────┐
 │ 32-byte signature block│ RC4( body )                  │
 └────────────────────────┴──────────────────────────────┘
```

### Signature block (32 bytes)

`+[PUBlockBuilder signatureBlockWithLength:section23Length:section4Length:]`
at `0x10000b819`:

| Offset | Size | Contents |
|---|---|---|
| 0  | 8 | `C0 C1 C2 C3 C4 C5 C6 C7` |
| 8  | 7 | body length, `%07d` |
| 15 | 1 | `0x00` |
| 16 | 4 | `"154\0"`, block format version |
| 20 | 5 | `section23Length`, `%05d` |
| 25 | 1 | `0x00` |
| 26 | 5 | `section4Length`, `%05d` |
| 31 | 1 | `0x00` |

`section23Length` is everything before the XML section, that is,
`len(section 1) + len(answers) + len(notify block)`. `section4Length` is the
length of the XML section alone. The two sum to the body length.

### Body

Concatenation of four parts, RC4-encrypted as a whole:

**Section 1: job data** (`+[PUBlockBuilder jobDataBlock]`). Four NUL-terminated
ASCII strings:

```
hostname \0 username \0 jobname \0 sidesImaged \0
```

**Sections 2 & 3: answers** (`+[PUBlockBuilder answerBlockForDescriptors:]`).
One record per descriptor. Descriptors of type `Guest` with an empty answer are
skipped.

```
name \0 answer \0                       # ordinary question
CC_Static \0 hierarchyLevel \r answer \0   # question with a hierarchy level
```

**Notify block** (`+[PUBlockBuilder staticNotifyIPBlock]`). The client shells out
to `ps waxoucomm | grep Notify | grep -v grep`; if no Pharos Notify daemon is
running it emits **nothing**. There is no Notify daemon on Linux, so this driver
always emits an empty block.

**Section 4: XML properties** (`+[PUBlockBuilder XMLPropertiesBlock]`). Pharos
AppTracker accounting metadata, ASCII, **no trailing NUL**:

```
<AppTrackerJob>
<ProcessExecutable>APP</ProcessExecutable>
<AppTrackerPages>N</AppTrackerPages>
<AppTrackerCopies>N</AppTrackerCopies>
</AppTrackerJob>
```

(Newlines are literal `\n` between the tags, exactly as shown.)

### RC4

Standard RC4 (`rc4_prepare_key` at `0x10000ec7f` is a textbook KSA) with a
**hard-coded 16-byte key** loaded from `0x10004a480`:

```
42 95 f2 a7 68 05 11 b4 c3 74 39 e1 d2 66 57 94
```

This is obfuscation, not encryption. The key ships in every Pharos client and
server. It is *not* the negotiated session key, which is why the popup block can
be built without ever talking to the popup server.

## 4. Delivery

Plain RFC 1179 to TCP 515 on the print server, with `[popup block][print data]`
as the data file and the NetID in the control file's `P` (user) line.

The vendor backend can additionally wrap the whole stream in AES-128-CBC after
asking the LPD server for a public key, but it falls back to plaintext when the
server offers none (`DEBUG: popup - failed to get public key from server,
sending plaintext`). DKU's server accepts plaintext, which is what this driver
sends.

## Reproducing the analysis

The scratch tooling used here was a small Mach-O parser plus Capstone:

* parse `LC_SEGMENT_64` / `LC_SYMTAB`, walk `__objc_classlist` to recover
  `class → method → IMP` addresses;
* annotate RIP-relative operands against `__cfstring`, `__objc_selrefs`,
  `__objc_classrefs` and the indirect symbol table to label `objc_msgSend`
  selectors and stub calls;
* bound each function by the next symbol address before disassembling.

That turns the stripped-of-nothing-but-readable Objective-C into traces like
`dataWithCapacity: → appendBytes:length: 8 → UTF8String → ...`, from which the
byte layouts above fall out directly.
