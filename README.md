# sius-ingest

`sius-ingest` captures the TCP stream exposed by SIUSData and forwards every
unique raw record to Supabase through a durable local SQLite outbox. A separate
normalizer can run on any other computer to build athlete sessions, sighter
blocks, match relays, and canonical shots from those immutable raw events.

The range Windows PC is only the SIUS-to-Supabase bridge. Parsing and projection
work can run on macOS, Linux, or Windows and can stop temporarily without losing
data. Both programs use only the Python standard library at runtime.

## Current behavior

- reconnects to SIUSData automatically;
- starts raw collection and background upload together when double-clicked;
- writes a lossless capture for future protocol analysis;
- retains every received record locally, including unknown and malformed ones;
- preserves SIUSData connection backlogs as raw observations while deduplicating
  their canonical shots;
- uploads only `sius_raw_events` from the range PC;
- keeps upload retry state in SQLite across restarts and internet outages;
- lets an external normalizer parse `_SHOT` and `_SHID` records;
- groups normalized shots by firing number, lane, sighter block, and match relay;
- starts a new relay on a sighter/match transition or reset shot counter;
- never assumes that a relay contains exactly 60 shots;
- checkpoints normalization only after its Supabase writes succeed;
- makes all normalized tables reproducible from raw events.

See [docs/protocol-observations.md](docs/protocol-observations.md) for the
evidence and explicit assumptions behind the parser.

## Requirements

- Python 3.11 or newer
- SIUSData TCP access, normally `127.0.0.1:4000` on the range PC
- optional Supabase project for remote storage

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

1. Open the repository's **Actions** tab.
2. Select **Build Windows executable**.
3. Choose **Run workflow** on the desired branch.
4. When the run finishes, download the
   `sius-ingest-windows-x64-...` artifact.
5. Extract both `sius-ingest.exe` and `SHA256SUMS.txt` into a permanent folder
   on the range PC.

The workflow is manual-only; it does not run for pushes or pull requests. The
artifact is retained by GitHub for 30 days. Python is not required on the PC
that runs the resulting executable. The executable is not currently
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

The range-PC result should show raw events and raw upload counts. Projection
counts belong to the normalizer's separate SQLite database.

## Configure Supabase

1. Create a Supabase project.
2. Run [supabase/schema.sql](supabase/schema.sql) in the SQL editor.
3. For the clean v0.3 cutover from an experimental installation, run
   [supabase/reset_experimental_data.sql](supabase/reset_experimental_data.sql)
   once. It permanently removes the previous SIUS rows.
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

## Run the normalizer elsewhere

Clone and install this repository on the Mac, server, or other computer that
will build the normalized tables. Save the same two Supabase variables, then
run:

```bash
set -a
source .env
set +a
sius-ingest normalize --watch
```

Alternatively, export `SUPABASE_URL` and `SUPABASE_SECRET_KEY` directly. The
application never writes those credentials into SQLite.

No manual SQLite setup is required. The worker creates
`data/sius-normalizer.sqlite3` and stores its durable raw-event checkpoint,
lane state, and projection outbox there. It reads `sius_raw_events` in
server-assigned `ingest_id` order and writes:

- `sius_sessions`;
- `sius_phases`;
- `sius_shots`.

Stopping the normalizer is safe. On restart it drains any pending projection
writes, resumes after the last committed raw event, and catches up. Run without
`--watch` for one catch-up pass:

```bash
sius-ingest normalize
```

Use an always-on machine if normalized tables need to update continuously. The
range-PC bridge continues preserving and forwarding raw data while the worker is
offline.

If the Supabase data is reset with `reset_experimental_data.sql`, also remove
the normalizer's local `data/sius-normalizer.sqlite3` before starting it again.
This is only necessary for an intentional destructive reset.

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
truth. Canonical shots from backlog retransmissions are deduplicated while the
raw observations remain available for auditing. Every exact TCP chunk also
remains available in the range PC's SQLite database and lossless capture
directory.

## Configuration

Frequently used options have environment-variable equivalents:

| Variable | Default | Purpose |
|---|---|---|
| `SIUS_HOST` | `127.0.0.1` | SIUSData host |
| `SIUS_PORT` | `4000` | SIUSData TCP port |
| `SIUS_OUTPUT` | `captures` | lossless capture parent directory |
| `SIUS_DATABASE` | `data/sius-raw.sqlite3` | range-PC raw outbox |
| `SIUS_NORMALIZER_DATABASE` | `data/sius-normalizer.sqlite3` | worker state |
| `SIUS_RANGE_ID` | `default-range` | stable range identifier |
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
        -> monotonic checkpoint
        -> conservative parser
        -> relay sessionizer
        -> SQLite projection outbox
        -> Supabase sessions + phases + shots
```

Key modules:

- `tcp_source.py`, `framing.py`, `capture.py` — byte-level acquisition;
- `parser.py`, `models.py` — observed protocol and typed domain records;
- `sessionizer.py` — deterministic lane/session/relay transitions;
- `outbox.py` — SQLite schema, transactions, deduplication, and outbox;
- `replay_source.py` — verified replay of previous captures;
- `remote_source.py` — ordered raw-event reads from Supabase;
- `normalizer.py` — checkpointed, replayable projection worker;
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
