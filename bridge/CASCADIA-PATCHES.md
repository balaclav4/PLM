# Cascadia patches and findings

Four things surfaced while building an integration between Cascadia's file
vault and an external CAD agent that works in FreeCAD. One is patched in this
tree; three are reported but untouched.

All four were invisible while reading the code. Every one of them appeared on
the first real API call, which is the argument for the round-trip test at the
bottom of this page.

Each is written to be pasted into an upstream issue or PR without editing.
Everything was found against a local instance at `635ff7b` — schema pushed,
minimal seed, PostgreSQL 16.

| #   | Finding                                                            | Severity          | State here              |
| --- | ------------------------------------------------------------------ | ----------------- | ----------------------- |
| 1   | FreeCAD files rejected by the upload allowlist                     | Blocks a workflow | **Patched**             |
| 2   | A superseded file version stays flagged as checked out             | Data hygiene      | Reported, worked around |
| 3   | The `anthropic` AI provider ignores `baseURL`                      | Inconsistency     | Reported                |
| 4   | Same-name upload forks a file, and `/versions` is not scoped to it | Data integrity    | Reported, worked around |

---

## 1. The vault rejects FreeCAD files — patched

**What happens.** Uploading a `.FCStd` returns `415 FILE_TYPE_NOT_ALLOWED`.

```
File type '.fcstd' is not allowed. Allowed types: .step, .stp, .iges, .igs,
.stl, .obj, .sldprt, .sldasm, .prt, .asm, .catpart, .catproduct, .x_t, .x_b,
.sat, .3mf, .glb, .gltf, .dwg, .dxf, .ipt, .iam, .idw, .3dm, .ply, .par, ...
```

**Why it matters.** The allowlist covers SolidWorks, CATIA, Creo/NX, Inventor,
Solid Edge, Fusion 360 and Rhino. FreeCAD is the only major MCAD system absent,
and it is the one Cascadia's own commercial edition does _not_ reserve a
connector for — so it is the CAD system an open-core user is most likely to
bring. As it stands, native FreeCAD documents cannot enter the vault at all,
and a FreeCAD shop can only store derived STEP.

This reads like an omission rather than a decision: nothing else in the vault
treats FreeCAD specially, and `.FCStd` is a plain ZIP container, no more
hazardous than the `.f3z` and `.zip` entries already allowed.

**Reproduce.**

```bash
curl -X POST http://localhost:3000/api/v1/items/<item-id>/files/upload \
  -H "Authorization: Bearer csc_..." -F file=@bracket.FCStd
# 415 FILE_TYPE_NOT_ALLOWED
```

**The patch.** `packages/core/src/lib/vault/utils/file-utils.ts`, four lists —
missing any one of them leaves FreeCAD files half-supported (uploadable but not
recognised as CAD, or CAD but miscategorised):

| Location                                | Change                                             |
| --------------------------------------- | -------------------------------------------------- |
| `ALLOWED_EXTENSIONS`                    | `.fcstd`, `.fcstd1` under a `// FreeCAD` heading   |
| `isCADFile`                             | same two, so FreeCAD documents count as CAD models |
| `categorizeFile` → `cadModelExtensions` | same two, for correct file-category inference      |
| `getCADFormat`                          | `.fcstd`/`.fcstd1` → `'FreeCAD'` for display       |

`.fcstd1` is FreeCAD's backup generation of the same format; accepting it
avoids a confusing near-miss when someone uploads a recovered file.

**Verification.** 23 existing `file-utils.test.ts` tests pass unchanged;
`eslint --max-warnings 0` and Prettier are clean; a full FCStd upload →
checkout → check-in round-trip then succeeds against a live instance.

**Note for whoever takes this upstream.** The allowlist is a module-level
`const` with no override — no environment variable, no admin setting. A site
that needs one more format has to patch and rebuild. Worth considering whether
`ALLOWED_EXTENSIONS` should be seeded into configuration, with the constant as
its default. That is a bigger change than this bug needs, so it is not included
here.

---

## 2. A superseded file version keeps `isCheckedOut: true` — not patched

**What happens.** Check a file out, check it back in with new content, and the
old version's row stays flagged as checked out forever.

```
v1  5c3f0c7f…   isCheckedOut: true    isLatestVersion: false   ← lock never cleared
v2  97c6247f…   isCheckedOut: false   isLatestVersion: true
```

`GET /api/v1/files/5c3f0c7f…/lock-status` keeps reporting `isLocked: true`
with the original `lockedBy` and `lockedAt`, indefinitely.

**Why it matters.** It is not blocking, because a superseded version is not the
head and nothing tries to lock it again. But:

- any client that remembers the id it checked out — the natural thing to do —
  sees a file that is permanently locked, with no way to tell that from a real
  lock held by a colleague;
- "who has what checked out" reporting over the file table overcounts, and the
  overcount grows with every check-in;
- an administrator looking at a stale lock has no way to distinguish an
  abandoned checkout from this artefact.

**Reproduce.**

```bash
curl -X POST .../files/$ID/checkout   -H "$AUTH"
curl -X POST .../files/$ID/checkin    -H "$AUTH" -F file=@edited.FCStd
curl       .../files/$ID/lock-status  -H "$AUTH"
# {"isLocked": true, "lockedBy": {...}, "lockedAt": "..."}
```

**Suggested fix.** In `FileService.checkInFile`, when a new version row is
created, clear `isCheckedOut`/`checkedOutBy`/`checkedOutAt` on the superseded
row in the same transaction. The lock is a property of "the file people are
working on", so it should retire with the version it was taken against.

A migration would want to clear the flag on existing rows where
`isLatestVersion` is false.

**Worked around by.** `cascadia_bridge` resolves the lineage head before every
checkout and reports the new head id after check-in, so it never asks about a
superseded id. That is defensive, not a fix.

---

## 3. The `anthropic` AI provider ignores `baseURL` — not patched

**What happens.** In `packages/core/src/lib/ai/adapters.ts`, three of four
providers honour a configured base URL and one does not:

```ts
case 'openai':    return createOpenaiChat(model, config.apiKey, { baseURL: config.baseURL })
case 'gemini':    return createOpenaiChat(model, config.apiKey, { baseURL: GEMINI_OPENAI_BASE_URL })
case 'ollama':    return createOpenaiChat(model, config.apiKey || 'ollama', { baseURL })
case 'anthropic': return createAnthropicChat(model, config.apiKey)   // ← no baseURL
```

**Why it matters.** Operators who front their model traffic with a gateway — an
LLM proxy, an egress-logging or policy layer, a self-hosted router — get that
for OpenAI and Ollama but silently not for Anthropic. `baseURL` is configurable
in the same settings UI for every provider, so the natural reading is that
setting it takes effect. Selecting `anthropic` quietly bypasses the gateway,
which is the failure mode you least want in a deployment that added one on
purpose: traffic leaves by a route the operator believes is closed.

For a PLM system holding engineering IP, that is worth more than a
configuration nicety.

**Suggested fix.** Pass the base URL through, if `createAnthropicChat` accepts
one:

```ts
case 'anthropic':
  return createAnthropicChat(model, config.apiKey, { baseURL: config.baseURL })
```

If the underlying adapter genuinely cannot take one, the honest alternative is
to reject a configured `baseURL` for this provider with a validation error, so
the setting cannot appear to apply when it does not.

**Worked around by.** Configuring Cascadia as the `openai` provider pointed at
the gateway's OpenAI-compatible endpoint.

---

## 4. Same-name uploads fork a file, and `/versions` is not scoped to one — not patched

Two behaviours that compound into a real ambiguity: there can be no single
answer to "what is the current version of this file?"

**4a — uploading an existing filename starts a parallel lineage.** Upload
`bracket.FCStd` to an item that already has one and Cascadia creates a second
independent chain at version 1 rather than adding version 2 to the existing
chain. Repeat it and every copy is a separate lineage, each marked
`isLatestVersion: true`:

```
bracket.FCStd  v1  isLatestVersion=true   id=0115ba8a
bracket.FCStd  v1  isLatestVersion=true   id=28d922a4
bracket.FCStd  v1  isLatestVersion=true   id=77cb0719
bracket.FCStd  v2  isLatestVersion=true   id=d9194f72
```

**4b — `GET /files/:fileId/versions` returns every file row on the item.** Not
the versions of the file whose id was passed — all of them, across unrelated
filenames. Both ids below return the identical seven rows, spanning three
different files:

```
versions(0115ba8a) -> 7 rows: [(d9194f72,v2,latest), (2986d227,v1), (28d922a4,v1,latest),
                               (77cb0719,v1,latest), (21dd33c8,v1), (0115ba8a,v1,latest),
                               (32d1e8e1,v1)]
versions(d9194f72) -> 7 rows: ... identical ...
```

**Why it matters.** A client asking the documented question — "give me the
versions of this file, and which is current" — gets an answer it cannot use.
Filtering by `fileName` narrows it, but 4a means several rows still claim to be
current, so any client that picks the first `isLatestVersion` row can land on a
different file's content entirely. That is a silent wrong-file edit, not an
error: the check-out succeeds, the bytes are simply someone else's.

We hit exactly that. An early version of the bridge resolved the head by taking
the first `isLatestVersion` row and downloaded content from an unrelated
lineage; the failure only surfaced because the test compared digests.

**Suggested fix.** They are separable:

- _4b_ is the smaller one: scope `/files/:fileId/versions` to the lineage the id
  belongs to. If "all versions of everything on this item" is a wanted view, it
  belongs on the item, not under a file id.
- _4a_ is the design question. Either an upload that collides with an existing
  filename on the same item should append a version to that chain, or it should
  be rejected as a conflict and require an explicit check-in. Silently forking
  is the one option that leaves the data ambiguous. Whichever is chosen,
  `isLatestVersion` should be unique per lineage, and ideally there should be a
  stable lineage identifier so that "the file" is addressable independently of
  which version happens to be current.

**Worked around by.** `cascadia_bridge.CascadiaClient.latest_version` filters
`/versions` by filename, returns the requested row unchanged when it is already
its own head, and raises `AMBIGUOUS_FILE_HEAD` rather than guessing when more
than one row claims to be current. Its test suite gives every run a unique
filename so it never provokes 4a.

---

## Reproducing any of this

```bash
npm run db:push && npm run db:seed
npm run dev
# create an API key: Settings → API Keys, or POST /api/v1/auth/api-keys

CASCADIA_API_KEY=csc_... CASCADIA_ITEM_ID=<uuid> \
  python bridge/tests/test_roundtrip.py     # 22 checks over the file lifecycle
```

The round-trip test is what surfaced findings 1 and 2 — both were invisible
while reading the code and appeared on the first real call.
