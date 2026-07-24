# sius-ingest

`sius-ingest` is a small, lossless TCP capture tool for exploring the data
emitted by SIUSData. The current version deliberately does **not** guess at the
SIUS message schema. Its job is to preserve enough evidence to determine the
stream's encoding, framing, message types, and field layout safely.

## What it captures

Each run creates a timestamped capture directory containing:

- `payload.bin` — every received payload byte, in arrival order
- `chunks.jsonl` — TCP receive chunks with timestamps, hashes, and Base64 data
- `records.jsonl` — best-effort newline-delimited records
- `connections.jsonl` — connection and disconnection events
- `session.json` — capture settings and final counters

TCP chunk boundaries are not protocol message boundaries. `payload.bin` and
`chunks.jsonl` are therefore the authoritative evidence; `records.jsonl` is a
convenient derived view.

Capture directories are ignored by Git so real range data and possible member
identifiers are not committed accidentally.

## Requirements

- Python 3.11 or newer
- Network access to the computer running SIUSData

No runtime packages outside the Python standard library are required.

## Installation

```bash
git clone https://github.com/eerriikk-pro/sius-ingest.git
cd sius-ingest
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

## Capture from the range Mac

With SIUSData running at `192.168.1.101:4000`:

```bash
sius-capture --host 192.168.1.101 --port 4000
```

The tool prints the capture directory and each complete newline-delimited
record it observes. Leave it running, fire the test shots, then press
`Control-C`. It reconnects automatically if the TCP connection drops.

To run directly from a checkout without installing:

```bash
PYTHONPATH=src python3 -m sius_ingest --host 192.168.1.101 --port 4000
```

Useful options:

```text
--output PATH            Parent directory for captures (default: captures)
--once                   Stop instead of reconnecting after a disconnect
--connect-timeout SEC    Connection timeout (default: 5)
--reconnect-delay SEC    Delay between retries (default: 2)
--quiet                  Do not print reconstructed records
```

Equivalent defaults can be supplied through `SIUS_HOST`, `SIUS_PORT`, and
`SIUS_OUTPUT`.

## Suggested first capture

1. Start the capture before shooting.
2. Fire three shots on one lane, several seconds apart.
3. Fire two shots on a second lane.
4. Reset or start a new practice on the first lane and fire two more shots.
5. Press `Control-C`.
6. Keep notes with each lane, displayed score, and approximate time.
7. Preserve any matching SIUSData export alongside the capture, but do not
   commit real range data to this repository.

## Development

Run the standard-library test suite:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The package is intentionally separated into:

- `tcp_source.py` — connection, receive, and reconnect behavior
- `framing.py` — tentative newline framing
- `capture.py` — lossless files and metadata
- `models.py` — typed events shared between those layers
- `cli.py` — the user-facing capture command

Parsing, durable outbox storage, and database uploading should be added only
after real captures establish the SIUS stream's shape.
