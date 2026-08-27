# cascadia-bridge

The FCStd round-trip between Cascadia PLM's file vault and the AI Mechanical
3DCAD Design Agent. A file leaves the vault into a design-job working copy and
comes back as a new version, carrying enough identity in both directions that
the check-in can prove which vault version the work descends from.

It is a client of two APIs, not a change to either system. Cascadia never opens
an FCStd; the agent never writes to Cascadia's database.

## Install

No third-party dependencies — it has to install cleanly alongside the design
agent without dragging an HTTP stack in behind it.

```bash
pip install -e bridge          # Python 3.12+
```

## Use

```bash
export CASCADIA_URL=http://localhost:3000
export CASCADIA_API_KEY=csc_...        # Cascadia → Settings → API Keys

cascadia-bridge checkout <file-id> --into ./job-workspace --eco <eco-id> --job <job-id>
# ... the agent and FreeCAD work on ./job-workspace/<name>.FCStd ...
cascadia-bridge status  --from ./job-workspace
cascadia-bridge checkin --from ./job-workspace --message "fillet added"
```

`checkout` writes a `.cascadia-bridge.json` sidecar next to the file recording
the vault file id, item id, version, SHA-256 at checkout, and the ECO and job
ids. `checkin` reads it back, compares digests, and mints a new version only if
the bytes actually changed.

## What it guarantees

- **Head resolution.** A Cascadia file id names *one version*, not the lineage.
  Checkout resolves to the current head first, so work never starts from a
  superseded revision.
- **Lock discipline.** The vault lock is taken before the download and released
  if anything afterwards fails — a stranded lock needs an administrator.
- **Integrity on the way out.** Downloaded bytes are checked against Cascadia's
  own recorded `fileHash` before work is allowed to start.
- **No accidental revisions.** An unedited working copy releases the lock
  without minting a version. Pass `--require-changes` to make that an error.
- **New head reported.** Check-in returns `head_file_id`, which differs from the
  id checked out — Cascadia mints a new row per version.

## Tests

Integration tests by necessity: lock discipline and version accounting do not
exist without a real vault.

```bash
CASCADIA_API_KEY=csc_... CASCADIA_ITEM_ID=<uuid> python bridge/tests/test_roundtrip.py
```

22 checks, covering upload, checkout, double-checkout rejection, no-op check-in,
edited check-in, head advance, lock release, and the sidecar guard rails.

## Two things to know

**FCStd support is a patch to Cascadia.** The vault's allowed-extension list is
a hardcoded constant that covers SolidWorks, CATIA, Inventor, Solid Edge, Fusion
and Rhino but omitted FreeCAD's own format, so uploads were rejected with
`FILE_TYPE_NOT_ALLOWED`. `packages/core/src/lib/vault/utils/file-utils.ts` now
lists `.fcstd`/`.fcstd1` in four places (allowlist, `isCADFile`, category
inference, format display name). Worth sending upstream.

**This directory's licence is undecided.** `npm run license:check` flags these
files because Cascadia's edition manifest treats everything in this tree as
AGPL-3.0-or-later by design, and no header has been added. Two ways to resolve
it, and they are not equivalent:

- Move `bridge/` to its own repository. It shares no code with Cascadia and
  talks to it over HTTP, so it stays proprietary-capable. Recommended.
- Run `npm run license:fix` to accept AGPL for it. Not reversible.
