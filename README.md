# sius-ingest

`sius-ingest` captures the TCP stream exposed by SIUSData and forwards every
unique raw record to Supabase through a durable local SQLite outbox. A
disposable daily worker builds athlete sessions, sighter blocks, match relays,
and canonical shots from those immutable raw events while keeping its durable
checkpoint and lane state in Supabase.

The range Windows PC is only the SIUS-to-Supabase bridge. Parsing and projection
work can run on macOS, Linux, or Windows and can stop temporarily without losing
data. Both programs use only the Python standard library at runtime.

## Current behavior

- reconnects after socket errors or when SIUSData closes the connection;
- enables TCP keepalive while leaving idle reconnect heuristics off by default;
- disables Windows QuickEdit so clicking the console cannot pause collection;
- starts raw collection and background upload together when double-clicked;
- writes a lossless capture for future protocol analysis;
- retains every received record locally, including unknown and malformed ones;
- suppresses stable shot and counter-event replays in the SQLite outbox while
  preserving the exact repeated bytes in the lossless capture;
- uploads only `sius_raw_events` from the range PC;
- keeps upload retry state in SQLite across restarts and internet outages;
- lets an external normalizer parse `_SHOT` and `_SHID` records;
- groups normalized shots by firing number, lane, sighter block, and match relay;
- starts a new relay on a sighter/match transition or reset shot counter;
- never assumes that a relay contains exactly 60 shots;
- commits normalization output, lane state, and its monotonic checkpoint in one
  Supabase transaction;
- processes only raw events newer than the remote checkpoint on normal runs;
- makes all normalized tables reproducible from raw events.

See [docs/protocol-observations.md](docs/protocol-observations.md) for the
evidence and explicit assumptions behind the parser.

## Requirements

- Python 3.11 or newer
- SIUSData TCP access, normally `127.0.0.1:4000` on the range PC
- optional Supabase project for remote storage
- Node.js 22.13 or newer for the local practice viewer

## Install

```bash
git clone https://github.com/eerriikk-pro/sius-ingest.git
cd sius-ingest
python -m venv .venv
```

On macOS or Linux:

```bash
source .venv/bin/activate
python -m pip install -e .
```

On Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

## Download a Windows executable

The repository includes a manual GitHub Actions build that produces a
self-contained 64-bit Windows console executable:

Download `sius-ingest.exe` and `SHA256SUMS.txt` from the latest public
[GitHub release](https://github.com/eerriikk-pro/sius-ingest/releases). Release
assets do not require a GitHub login.

Maintainers can also open the repository's **Actions** tab, select
**Build Windows executable**, and manually build any branch, tag, or commit.
Providing a matching `release_tag` such as `v0.4.2` creates or updates the public
release assets.

The workflow is manual-only; it does not run for pushes or pull requests. The
build artifact is retained by GitHub for 30 days. Python is not required on the
PC that runs the resulting executable. The executable is not currently
code-signed, so Windows may identify its publisher as unknown.

Place `sius-ingest.exe` in a permanent folder on the range PC. With SIUSData
running, double-click the executable to begin raw collection using the defaults.
If `SUPABASE_URL` and `SUPABASE_SECRET_KEY` are saved in the Windows environment,
the same process continuously forwards raw events. It does not build or upload
shots, sessions, or relays. The console remains open and shows connection,
capture, and upload activity; press `Control-C` to stop cleanly.

The equivalent explicit PowerShell command is:

```powershell
.\sius-ingest.exe run `
  --host 127.0.0.1 `
  --port 4000 `
  --range-id my-range `
  --database data\sius-raw.sqlite3
```

Launching without arguments is equivalent to `run`. It uses
`127.0.0.1:4000`, range ID `default-range`, SQLite database
`data\sius-raw.sqlite3`, and capture directory `captures\`. If either Supabase
setting is missing, it clearly reports that upload is disabled and continues
collecting locally.

On Windows, the collector disables the console's QuickEdit mode at startup and
prints a confirmation. This prevents an accidental click or text selection from
pausing the entire process. Normal reconnects after socket errors and peer
closures remain enabled, as does TCP keepalive.

Idle health logs and forced idle reconnects are disabled by default because a
quiet range is indistinguishable from a silent stream. They remain available as
explicit diagnostics: set `SIUS_HEALTH_INTERVAL_SECONDS` or
`SIUS_IDLE_RECONNECT_SECONDS` to a positive number of seconds. SIUSData may
replay its current backlog after any reconnect; stable shot and counter records
already seen by the raw bridge are not queued or uploaded again.

Upgrading the executable does not replace `.env`, `captures/`, or
`data/sius-raw.sqlite3`. Stop the old process, replace only the executable and
checksum, then start it again from the same directory. Pending raw uploads
remain in SQLite.

To verify the download against the generated checksum:

```powershell
Get-FileHash .\sius-ingest.exe -Algorithm SHA256
Get-Content .\SHA256SUMS.txt
```

Developers can create the same executable from a Windows checkout:

```powershell
.\scripts\build_windows.ps1
```

## Run the range-PC raw bridge

On the SIUSData Windows PC:

```powershell
sius-ingest run `
  --host 127.0.0.1 `
  --port 4000 `
  --range-id my-range `
  --database data\sius-raw.sqlite3
```

For the currently tested Mac-to-PC connection:

```bash
sius-ingest run \
  --host 192.168.1.101 \
  --port 4000 \
  --range-id my-range \
  --database data/sius-raw.sqlite3
```

The command prints one summary per captured shot while retaining every message
type. It also creates a timestamped
directory under `captures/` with:

- `payload.bin` — all received payload bytes in arrival order;
- `chunks.jsonl` — exact TCP chunks, timestamps, hashes, and Base64 data;
- `records.jsonl` — reconstructed newline-delimited records;
- `connections.jsonl` — connection and disconnection events;
- `session.json` — capture settings and final counters.

Press `Control-C` to stop cleanly. Both `captures/` and local database files
are ignored by Git because they can contain member information.

To print every raw record as well as shot summaries, add
`--verbose-records`. The original capture-only command remains available:

```bash
sius-capture --host 192.168.1.101 --port 4000
```

## Replay a capture into the raw outbox

Captured data can be parsed again without SIUSData:

```bash
sius-ingest replay \
  captures/sius-20260725T000127Z \
  --range-id my-range \
  --database data/sius-raw.sqlite3
```

Replay verifies the hash of each captured record by default. Use `upload` after
replay to forward its raw events. Replaying the same capture with its original
connection and sequence metadata is idempotent. A newly observed reconnect
backlog is retained as new raw observations but does not duplicate canonical
shots.

## Inspect local status

```bash
sius-ingest status --database data/sius-raw.sqlite3
sius-ingest status --database data/sius-raw.sqlite3 --json
```

The range-PC result should show raw events and raw upload counts. Sessions,
phases, and shots are built remotely and therefore remain zero in this local
database.

## Configure Supabase

1. Create a Supabase project.
2. Run [supabase/schema.sql](supabase/schema.sql) in the SQL editor.
3. For the v0.4 normalizer cutover, run
   [supabase/reset_projection.sql](supabase/reset_projection.sql) once. It
   preserves every raw event while clearing the rebuildable sessions, phases,
   shots, lane state, errors, and checkpoint.
4. Copy the project URL from the project's **Connect** dialog.
5. In **Settings > API Keys**, create a server-side secret key.
6. Supply `SUPABASE_URL` and `SUPABASE_SECRET_KEY` to both processes.

The `sb_secret_...` key bypasses row-level security and grants elevated access.
Never commit it or put it in a browser/mobile application. On a shared range
PC, use a temporary test key and delete it from Supabase after testing. A
restricted ingestion endpoint should replace it before permanent unattended
deployment.

On a trusted Windows range computer, save both values once through
**Edit environment variables for your account**:

```text
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SECRET_KEY=sb_secret_replace_me
```

Restart any open consoles after saving them. From then on, double-clicking
`sius-ingest.exe` starts raw collection and forwarding automatically.

On a shared PC, provide the URL on the command line and let the collector read
the temporary key from a masked prompt:

```powershell
.\sius-ingest.exe run `
  --url https://your-project.supabase.co `
  --prompt-secret-key
```

Collection does not depend on Supabase being reachable. Network or API failures
remain in the SQLite outbox and are retried with backoff.

The standalone `live` and `upload --watch` commands remain available for
diagnostics and split-process deployments. `upload` sends raw events only.

## Run the durable normalizer

The normalizer is a one-shot command. It stores no local checkpoint or outbox:
all durable progress lives in Supabase. Save the same two Supabase variables
and run:

```bash
set -a
source .env
set +a
sius-ingest normalize
```

Alternatively, export `SUPABASE_URL` and `SUPABASE_SECRET_KEY` directly. No
manual SQLite setup is required. The worker reads `sius_raw_events` after the
server-side checkpoint in `ingest_id` order and writes:

- `sius_sessions`;
- `sius_phases`;
- `sius_shots`.

Each page commits its sessions, phases, shots, errors, per-lane state, and
checkpoint through one PostgreSQL function. A failed request leaves the
checkpoint unchanged, so rerunning is safe. Duplicate shot observations advance
the raw cursor without changing relay state or canonical shot counts.

The included **Normalize Supabase practice data** GitHub Actions workflow runs
daily at 03:17 in `America/Vancouver` and can also be started manually:

1. Add repository Actions secrets named `SUPABASE_URL` and
   `SUPABASE_SECRET_KEY`.
2. Open **Actions > Normalize Supabase practice data**.
3. Choose **Run workflow** for the initial backfill.
4. Confirm its ending cursor matches the newest raw `ingest_id`.
5. Run it a second time and confirm it reports zero new events.

The repository is public, so standard GitHub-hosted runners are free. GitHub
can disable scheduled workflows after 60 days without repository activity; if
that happens, re-enable the workflow and run it manually. The remote checkpoint
will catch up every missed event rather than relying on a two- or three-day
lookback.

Use [supabase/reset_projection.sql](supabase/reset_projection.sql) for a
controlled rebuild after an incompatible parser/sessionizer version change. The
normalizer refuses to mix different projection versions silently.

## Run the local practice viewer

The proof-of-concept viewer lives in [`web/`](web/). It looks up a firing
number, accepts a configurable 1–365 day window, and displays normalized shots
using the stored session, sighter-block, and match-relay boundaries. Match
relays are not split at an arbitrary 60 shots.

The viewer reads the existing repository-level `.env` file. Its Next.js route
handler queries Supabase on the server, so `SUPABASE_SECRET_KEY` is never sent
to browser code.

```bash
cd web
npm install
npm run dev
```

Open <http://127.0.0.1:3000>, enter a member ID, and choose the number of days
to inspect. `SIUS_RANGE_ID` is optional; when present, the viewer limits results
to that range. `SIUS_VIEWER_TIMEZONE` controls displayed dates and defaults to
`America/Vancouver`.

The target display uses the scale inferred from the controlled SIUS capture:
native X/Y coordinates are multiplied by 1000 to plot millimetres. The raw
native values remain unchanged in Supabase.

### Data retained remotely

Supabase receives every observed SIUS record, not only shots. Each raw event
contains:

- the complete original record as text and Base64 bytes;
- every semicolon-delimited field in order;
- original delimiter, byte length, and SHA-256 hash;
- connection ID, record sequence, and server-assigned ingestion order;
- an observation key plus a stable content/event correlation key;
- local receive timestamp and available SIUS time/counter fields;
- firing point, lane, and shooter identifiers when present;
- parser version, parsed payload, unknown fields, and parse errors.

The external normalizer additionally retains athlete sessions, sighter/match
phases, scores, raw score fields, shot flags, coordinates, and the full parsed
`_SHOT` payload. These tables are projections: raw events remain the source of
truth. Canonical shots from backlog retransmissions are deduplicated. The first
stable raw event remains in SQLite and Supabase, while every exact TCP byte
received—including repeated backlog observations—remains in the range PC's
lossless capture directory.

## Configuration

Frequently used options have environment-variable equivalents:

| Variable | Default | Purpose |
|---|---|---|
| `SIUS_HOST` | `127.0.0.1` | SIUSData host |
| `SIUS_PORT` | `4000` | SIUSData TCP port |
| `SIUS_OUTPUT` | `captures` | lossless capture parent directory |
| `SIUS_DATABASE` | `data/sius-raw.sqlite3` | range-PC raw outbox |
| `SIUS_RANGE_ID` | `default-range` | stable range identifier |
| `SIUS_IDLE_RECONNECT_SECONDS` | disabled | optionally replace an idle TCP stream |
| `SIUS_HEALTH_INTERVAL_SECONDS` | disabled | optional idle connection log interval |
| `SIUS_VIEWER_TIMEZONE` | `America/Vancouver` | local viewer display timezone |
| `SUPABASE_URL` | none | Supabase project URL |
| `SUPABASE_SECRET_KEY` | none | private `sb_secret_...` uploader credential |

Run `sius-ingest COMMAND --help` for all command-specific options.

## Architecture

Raw collection and derived projections are deliberately independent:

```text
Range PC
    SIUSData TCP
        -> lossless capture
        -> newline framing
        -> SQLite raw events + durable raw outbox
        -> Supabase sius_raw_events

External worker
    Supabase sius_raw_events
        -> remote monotonic checkpoint + lane state
        -> conservative parser
        -> relay sessionizer
        -> atomic Supabase RPC
        -> sessions + phases + shots + errors

Local viewer
    Browser
        -> server-only viewer API
        -> Supabase sessions + phases + shots
```

Key modules:

- `tcp_source.py`, `framing.py`, `capture.py` — byte-level acquisition;
- `parser.py`, `models.py` — observed protocol and typed domain records;
- `sessionizer.py` — deterministic lane/session/relay transitions;
- `outbox.py` — range-PC SQLite schema, transactions, and raw upload outbox;
- `replay_source.py` — verified replay of previous captures;
- `remote_source.py` — ordered raw-event reads from Supabase;
- `projection.py` — pure shot/session/relay projection engine;
- `remote_projection.py` — Supabase checkpoint, lane state, and atomic commits;
- `normalizer.py` — incremental, remotely durable projection orchestration;
- `uploader.py` — scoped, idempotent Supabase PostgREST uploads;
- `app.py` — operational `run`, `replay`, `status`, `upload`, and `normalize`
  commands.

Unknown fields keep `*_raw` names, and every parsed record retains its complete
field list. Improving the parser therefore does not require recollecting old
data.

## Development

Install development tools and run all checks:

```bash
python -m pip install -e '.[dev]'
ruff check .
ruff format --check .
PYTHONPATH=src python -m unittest discover -s tests -v
```

Tests use synthetic firing numbers and records. Real captures and athlete names
must not be committed.

Run the viewer checks separately:

```bash
cd web
npm install
npm run lint
npm run typecheck
npm test
npm run build
```
