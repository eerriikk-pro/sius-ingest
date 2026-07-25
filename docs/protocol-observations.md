# Observed SIUSData TCP protocol

This document records controlled observations from SIUSData's TCP server on
port 4000. It is not an official SIUS protocol specification. Fields that have
not been confirmed retain neutral or `*_raw` names in the code.

Parser version: `observed-v1`

## Transport and connection behavior

- The server was listening on `0.0.0.0:4000`.
- The stream was newline-delimited, semicolon-separated text.
- SIUSData immediately emitted roughly 500 historical records after a client
  connected, then continued with new events.
- A single physical shot caused related messages such as `_GRPH`, `_SHOT`, and
  `_TOTL`.
- TCP receive boundaries are not assumed to be record boundaries.

The collector retains both raw TCP chunks and reconstructed records. Local raw
observations include connection identity and sequence, while canonical shot
keys are stable across reconnects and capture replay.

## Common prefix

Many observed records begin with:

```text
type;firing_point_index;lane_number;shooter_number;...
```

For physical lane 6:

```text
firing_point_index = 5
lane_number = 6
```

The implementation stores both rather than deriving one from the other.

## `_SHOT` observed-v1 mapping

Example match shot:

```text
_SHOT;5;6;513;60;23;17:16:22.75;3;31;7;73;0;0;1;0.00680121;-0.00609518;900;0;0;655.35;1768809600;61;450;734
```

| Index | Code name | Example | Confidence |
|---:|---|---:|---|
| 0 | `record_type` | `_SHOT` | confirmed |
| 1 | `firing_point_index` | `5` | confirmed by lane test |
| 2 | `lane_number` | `6` | confirmed by lane test |
| 3 | `shooter_number` | `513` | confirmed by firing-number test |
| 4 | `stream_code_raw` | `60` | unknown |
| 5 | `event_sequence` | `23` | observed monotonic per lane stream |
| 6 | `device_time_text` | `17:16:22.75` | observed time of day |
| 7 | `message_code_raw` | `3` | unknown |
| 8 | `exercise_code_raw` | `31` | likely exercise/discipline, unconfirmed |
| 9 | `shot_flags_raw` | `7` | sighter/match bit confirmed |
| 10 | `primary_score_raw` | `73` | score encoding depends on exercise |
| 11 | `secondary_score_raw` | `0` | score encoding depends on exercise |
| 12 | `indicator_raw` | `0` | unknown |
| 13 | `shot_number` | `1` | confirmed by controlled sequence |
| 14 | `x_native` | `0.00680121` | shot X coordinate, native units unconfirmed |
| 15 | `y_native` | `-0.00609518` | shot Y coordinate, native units unconfirmed |
| 16 | `distance_raw` | `900` | likely target distance/config, unconfirmed |
| 17 | `unknown_17_raw` | `0` | unknown |
| 18 | `unknown_18_raw` | `0` | unknown |
| 19 | `sentinel_raw` | `655.35` | likely unavailable-value sentinel |
| 20 | `annual_ticks` | `1768809600` | likely SIUS annual time counter |
| 21 | `target_type_raw` | `61` | target/config value, unconfirmed |
| 22 | `target_width_raw` | `450` | target/config value, unconfirmed |
| 23 | `target_id_raw` | `734` | target hardware/config ID, unconfirmed |

All fields, including any future trailing fields, are also retained verbatim in
the parsed JSON payload and original raw event.

## Sighter and match classification

Controlled shots produced:

```text
sighter: shot_flags_raw = 39
match:   shot_flags_raw = 7
```

The difference is bit `0x20`, so `observed-v1` classifies a shot as a sighter
when that bit is set. A future capture containing a different flag combination
should be validated before changing this rule.

The range workflow guarantees that sighters do not occur inside a match relay.
The sessionizer consequently treats:

- sighter to match as the start of a match relay;
- match to sighter as the end of the preceding match relay;
- a non-increasing shot number as a new phase, including a new match relay
  started without intervening sighters;
- relay length as open-ended rather than fixed at 60.

## Score normalization

Two encodings have been observed:

```text
...;9;94;...   -> 9.4
...;94;0;...   -> 9.4
```

The canonical database stores `score_tenths = 94` and `score_integer = 9`.
Both raw score columns remain available for auditing and future exercise
support.

## Athlete identity

Entering firing number `513` produced:

```text
_SHID;5;6;513;1;513
_NAME;5;6;513;0;...
```

Subsequent `_SHOT` records carried `513` in field 3. The collector associates
shots using the value on each `_SHOT`, not by trusting a previous `_SHID` or
`_NAME` message. Zero and blank values are stored as anonymous.

The controlled test also showed that entering a firing number did not
retroactively identify prior shots. The new identity became active after the
target returned to a new practice sequence.

## Session boundaries

An athlete lane session begins with the first accepted shot for a lane. A new
session begins when:

- the `_SHOT` firing number changes, including anonymous to identified;
- the annual device counter indicates a gap longer than the configurable
  timeout (four hours by default);
- as a fallback, the collector receive timestamps indicate the same idle gap.

The annual counter advanced by approximately 100 ticks per second during the
controlled sequence. Using it for relative gaps is important because SIUSData
can replay hours or days of historical shots within seconds of connection.
The code deliberately does not convert that counter into a calendar timestamp;
the range timezone and year-rollover behavior still require validation.

Athlete handoff behavior beyond those rules is intentionally deferred until
more controlled range tests are available. Session and phase IDs are
deterministic, so replay creates the same grouping.

## Deduplication

SIUSData's connection backlog means receive timestamp alone cannot identify a
shot. The canonical key currently combines:

- configured range ID;
- lane number;
- annual counter;
- event sequence;
- shot number;
- hash of the raw `_SHOT` record.

Every arrival is retained in local `raw_events`, but identical shots produce
only one canonical `shots` row and one remote raw event. This preserves local
evidence while preventing reconnects from multiplying athlete results.

## Other observed message types

Captures included `_DIAG`, `_GRPH`, `_NAME`, `_PRCH`, `_PRST`, `_SHID`,
`_SNAT`, `_STAT`, `_SUBT`, `_TEAM`, and `_TOTL`. They are retained and
generically parsed for common prefix/timestamp values, but they do not drive
relay grouping yet.

`_TOTL` matched the accumulated match score in the controlled test and omitted
sighters. It is valuable validation evidence, but `_SHOT` remains the canonical
per-shot source.

## Future range validation

Useful follow-up captures include:

- another lane and target model;
- both rifle and pistol exercises;
- a match relay restarted directly into match mode;
- deliberate athlete handoff with and without a target reset;
- a year boundary or SIUSData clock adjustment;
- deletion, correction, crossfire, and missed-shot workflows;
- SIUSData restart versus collector-only reconnect.

Until then, unknown messages and fields must remain losslessly preserved rather
than assigned speculative semantics.
