# aura-frame-uploader

Publish photos to an [Aura](https://auraframes.com) digital picture frame from
the command line.

```bash
aura-upload                          # everything in the current directory
aura-upload ~/exports/selects/       # a folder
aura-upload photo.jpg --frame <id>   # one file
```

Aura offers no public API, and no maintained tool for putting photos on a frame
programmatically. This one drives the same private API the Aura apps use. It is
unofficial and unaffiliated — see [Stability](#stability).

## What it does

- Uploads a file or a folder, defaulting to the working directory.
- **Never duplicates a photo.** Each upload carries a `local_identifier` that
  Aura treats as an idempotency key — uploading the same one again updates the
  existing asset rather than adding a second copy. Losing your local records
  cannot produce duplicates.
- **Dates photos correctly.** Aura ignores EXIF inside the uploaded file and
  displays whatever the upload call says, so capture time is read locally from
  EXIF and sent explicitly. Without this, every photo shows as taken today.
- Resizes to 2048px on the long edge (what Aura's own web uploader does),
  converts to sRGB, bakes in EXIF rotation, and stays under Aura's 9.5 MB limit.
- Lists what is actually on a frame, removes assets, and can force a specific
  photo onto the screen immediately.

## Safety: the frame allowlist

An Aura account frequently includes frames belonging to **other people** —
family members who shared theirs with you — and your credentials can write to
all of them. Sending your holiday photos to your grandmother's frame is a
one-typo mistake.

So every write is refused unless the target frame is explicitly allowlisted:

```toml
allowed_frame_ids = ["00000000-0000-0000-0000-000000000000"]
```

No configuration means **nothing can be published**. The tool never falls back
to "the only frame" or matches on frame name — both are silent-mistake
generators. `aura-upload frames` marks which frames are allowed.

## Install

Requires Python 3.10+.

```bash
git clone https://github.com/louiekotler/aura-frame-uploader
cd aura-frame-uploader
python3 -m venv .venv && ./.venv/bin/pip install -e .

cp config.example.toml ~/.config/aura-upload/config.toml   # then edit it
./.venv/bin/aura-upload login --email you@example.com
./.venv/bin/aura-upload frames                             # copy the id you want
```

Your password is used once to obtain a token and is never written to disk. The
token is stored in the system keyring (macOS Keychain).

## Commands

| Command | |
|---|---|
| `login` / `logout` / `whoami` | authenticate; inspect the stored session |
| `frames` | list frames, marking which are allowlisted |
| `upload [PATH]` | upload a file or folder, default `.` |
| `list` | list what is actually on a frame |
| `remove` | remove an asset by identifier or asset id |
| `show` | display a specific photo on the frame now |

Useful `upload` flags: `--dry-run`, `--recursive`, `--max N`, `--delay SECONDS`,
`--force` (re-upload something already present), `--keep-going` (continue past
failures), `--json`.

By default `upload` skips photos whose identifier is already on the frame, and
stops on the first failure — Aura's rate limits are undocumented and unmeasured,
so it errs toward not hammering a failing API.

## Stability

This talks to a private API that Aura does not document or support, discovered
by observing the app's own traffic. **It can break at any time.** Nothing here
is endorsed by or affiliated with Aura.

If it does break, the frame's email address still works from any mail client —
that path is official, and needs no software.

## Credits

The upload flow was originally worked out by others, and this project would have
taken far longer without them:

- [zmanowar/auraframes](https://github.com/zmanowar/auraframes) — mapped the
  three-step upload, the S3 bucket and the Cognito identity pool.
- [meub/aura-frame-downloader](https://github.com/meub/aura-frame-downloader) —
  actively maintained, and the reference for the login payload.
- [bp1222/auraframes-api](https://github.com/bp1222/auraframes-api) — an
  OpenAPI sketch of the REST surface.

This is an independent implementation rather than a fork or a copy of any of
them: it covers only the handful of calls needed to publish photos, and was
verified end to end against a real frame.

## License

MIT
