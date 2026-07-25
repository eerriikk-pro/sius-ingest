# sius-ingest

`sius-ingest` captures the TCP stream exposed by SIUSData, preserves the
original bytes, parses the observed practice-shot format, groups shots into
sighter blocks and match relays, and stores everything in a durable local
SQLite database. An optional uploader synchronizes the local outbox to
Supabase/Postgres.

The collector is intended to run beside SIUSData on the range Windows PC, but
the same commands work on macOS for development and capture replay. It uses
only the Python standard library at runtime.

## Current behavior

- reconnects to SIUSData automatically;
- writes a lossless capture for future protocol analysis;
- retains every received record locally, including unknown and malformed ones;
- parses the `_SHOT` and `_SHID` shapes observed at this range;
- associates shots with the firing number carried by `_SHOT`;
- distinguishes sighters from match shots;
- starts a new relay on a sighter/match transition or reset shot counter;
- does not assume a relay contains exactly 60 shots;
- deduplicates SIUSData's connection backlog and replayed captures;
- commits each shot, relay update, and upload job in one SQLite transaction;
- uploads idempotently to Supabase with retry state kept in SQLite.

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
running, double-click the executable to begin live collection using the
defaults. The console window remains open and shows connection and shot
activity; press `Control-C` to stop cleanly.

The equivalent explicit PowerShell command is:

```powershell
.\sius-ingest.exe live `
  --host 127.0.0.1 `
  --port 4000 `
  --range-id my-range `
  --database data\sius.sqlite3
```

Launching without arguments uses `127.0.0.1:4000`, range ID `default-range`,
SQLite database `data\sius.sqlite3`, and capture directory `captures\`.

To verify the download against the generated checksum:

```powershell
Get-FileHash .\sius-ingest.exe -Algorithm SHA256
Get-Content .\SHA256SUMS.txt
```

Developers can create the same executable from a Windows checkout:

```powershell
.\scripts\build_windows.ps1
```

## Collect and store live data

On the SIUSData Windows PC:

```powershell
sius-ingest live `
  --host 127.0.0.1 `
  --port 4000 `
  --range-id my-range `
  --database data\sius.sqlite3
```

For the currently tested Mac-to-PC connection:

```bash
sius-ingest live \
  --host 192.168.1.101 \
  --port 4000 \
  --range-id my-range \
  --database data/sius.sqlite3
```

The command prints one summary per accepted shot. It also creates a timestamped
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

## Replay a capture

Captured data can be parsed again without SIUSData:

```bash
sius-ingest replay \
  captures/sius-20260725T000127Z \
  --range-id my-range \
  --database data/sius.sqlite3
```

Replay verifies the hash of each captured record by default. Replaying the
same capture, or receiving the same backlog after reconnecting, does not create
duplicate canonical shots.

## Inspect local status

```bash
sius-ingest status --database data/sius.sqlite3
sius-ingest status --database data/sius.sqlite3 --json
```

The result includes raw-event, shot, session, relay, pending-upload, and
failed-upload counts.

## Configure Supabase

1. Create a Supabase project.
2. Run [supabase/schema.sql](supabase/schema.sql) in the SQL editor.
3. Copy the project URL from the project's **Connect** dialog.
4. In **Settings > API Keys**, create a server-side secret key.
5. Supply `SUPABASE_URL` and `SUPABASE_SECRET_KEY` to the uploader process.

The `sb_secret_...` key bypasses row-level security and grants elevated access.
Never commit it or put it in a browser/mobile application. On a shared range
PC, use a temporary test key and delete it from Supabase after testing. A
restricted ingestion endpoint should replace it before permanent unattended
deployment.

On a shared PC, provide the URL on the command line and let the collector read
the temporary key from a masked prompt:

```powershell
.\sius-ingest.exe upload `
  --watch `
  --url https://your-project.supabase.co `
  --prompt-secret-key
```

For a trusted server, the equivalent environment configuration is:

```bash
export SUPABASE_URL=https://your-project.supabase.co
export SUPABASE_SECRET_KEY=sb_secret_replace_me
sius-ingest upload --watch
```

Collection does not depend on Supabase being reachable. Network or API
failures remain in the SQLite outbox and are retried with backoff.

### Data retained remotely

Supabase receives every unique SIUS record, not only shots. Each raw event
contains:

- the complete original record as text and Base64 bytes;
- every semicolon-delimited field in order;
- original delimiter, byte length, and SHA-256 hash;
- connection ID and record sequence;
- local receive timestamp and available SIUS time/counter fields;
- firing point, lane, and shooter identifiers when present;
- parser version, parsed payload, unknown fields, and parse errors.

Normalized tables additionally retain athlete sessions, sighter/match phases,
scores, raw score fields, shot flags, coordinates, and the full parsed `_SHOT`
payload. Identical backlog retransmissions are deduplicated remotely; every
arrival and exact TCP chunk remains available in local SQLite and the lossless
capture directory.

## Configuration

Frequently used options have environment-variable equivalents:

| Variable | Default | Purpose |
|---|---|---|
| `SIUS_HOST` | `127.0.0.1` | SIUSData host |
| `SIUS_PORT` | `4000` | SIUSData TCP port |
| `SIUS_OUTPUT` | `captures` | lossless capture parent directory |
| `SIUS_DATABASE` | `data/sius.sqlite3` | local SQLite database |
| `SIUS_RANGE_ID` | `default-range` | stable range identifier |
| `SUPABASE_URL` | none | Supabase project URL |
| `SUPABASE_SECRET_KEY` | none | private `sb_secret_...` uploader credential |

Run `sius-ingest COMMAND --help` for all command-specific options.

## Architecture

The transport and storage layers are deliberately independent:

```text
SIUSData TCP
    -> lossless capture
    -> newline framing
    -> conservative parser
    -> relay sessionizer
    -> SQLite events + canonical shots + outbox
    -> optional Supabase uploader
```

Key modules:

- `tcp_source.py`, `framing.py`, `capture.py` — byte-level acquisition;
- `parser.py`, `models.py` — observed protocol and typed domain records;
- `sessionizer.py` — deterministic lane/session/relay transitions;
- `outbox.py` — SQLite schema, transactions, deduplication, and outbox;
- `replay_source.py` — verified replay of previous captures;
- `uploader.py` — ordered, idempotent Supabase PostgREST uploads;
- `app.py` — operational `live`, `replay`, `status`, and `upload` commands.

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
