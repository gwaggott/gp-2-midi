# Humanised MIDI output: status and plan

Started 2026-10-14. **Goal:** make `gp2midi.py` output sound less mechanical
with two effects. The first is a slight random variation of velocity around
the score's dynamics. The second is a short spread between the notes of a
chord, as a pick crosses the strings, in the stroke direction.
**Status:** all steps (1–6) done.

## Ground rules

- **On by default.** Steps 2, 4 and 5 deliberately change the default
  output. `--no-humanize` turns every effect off, and with it every `.mid`
  must stay byte-identical to the output from before this work. Check this
  at each step with the baseline / diff commands in `docs/refactoring.md`
  (ground rules), adding `--no-humanize` to the "after" run.
- **Reproducible.** Randomness comes from a seeded generator (`--seed`), so
  two runs with the same switches write identical files.
- `.venv/bin/python -m pytest test` passes after every step. `MidiOptions`
  defaults match the CLI, so `humanize` defaults to True there too.
  `conftest.convert` passes `humanize=False` unless a test asks for it, so
  the existing tests' expectations don't change. Tests that call
  `track_to_midi` or the helpers directly with `MidiOptions()` must also
  be checked.
- `gpif` gets the parsing (stroke directions) and keeps no `mido`
  dependency. The randomness and timing live in `gp2midi.py`.
- One step per commit. Update this file (the status table and that step's
  notes), CLAUDE.md and `docs/articulations.md` in the same commit.

## Status

| # | Step | Size | Status |
|---|---|---|---|
| 1 | `--humanize` / `--no-humanize` switch and seeded random generator | S | **Done** (2026-10-14) |
| 2 | Velocity randomisation | S | **Done** (2026-10-14) |
| 3 | Pick direction of each onset | M | **Done** (2026-10-15) |
| 4 | Strum spread for pick strokes | M | **Done** (2026-10-15) |
| 5 | Brush and arpeggio directions | M | **Done** (2026-10-15) |
| 6 | Docs and listening pass | S | **Done** (2026-10-15) |

## Switches

Humanising is on by default; `--no-humanize` turns it all off. Setting
one of the values below to 0 turns just that effect off. Each switch follows the usual pattern: a
`DEFAULT_*` constant, a `MidiOptions` field, the argparse switch and its
clamp in `main`.

| Switch | Default | Meaning |
|---|---|---|
| `--humanize` / `--no-humanize` | on | turn the effects below on or off |
| `--seed N` | 0 | random seed |
| `--velocity-spread N` | 5 | random velocity offset of up to ±N per onset |
| `--strum-time MS` | 6 | delay per string for a pick stroke |
| `--brush-time MS` | 15 | delay per string for a scored brush (strum) |
| `--arpeggio-time MS` | 40 | delay per string for a scored arpeggio |

The defaults are starting points, to be tuned by listening (step 6).
Spread times are in milliseconds rather than ticks, unlike the other
timing switches, so a strum takes the same real time at any tempo.

## What the input files contain

- **Pick strokes:** no file in `in/` has one. As far as we know, GP7/8
  writes a Beat property `<Property name="PickStroke"><Direction>Up</Direction></Property>`
  (`Down` for a downstroke), in the same form as `Brush`. This is unconfirmed
  and there is no sample file, so the parser is tested with inline
  fragments only. Confirm it once a file with pick strokes is available.
- **Brush:** 317 beats in 10 files, 304 down and 13 up, written as
  `<Property name="Brush"><Direction>Down</Direction></Property>` (GP8 and
  GP6). Most are in one file (251).
- **Arpeggio:** 40 beats, 39 down and 1 up, written as
  `<Arpeggio>Down</Arpeggio>` on the Beat, in 4 files (32 in one nylon
  guitar part).
- **Mixed accents or ghost notes within a chord:** found in 9 files. One
  has 21 chords with an accented note and 3 with a ghost note; others have
  12, 6 and 4 chords with a ghost note, and a `.gpx` file 2 accented ones.
  These are the end-to-end checks for step 2.

## Step 1: `--humanize` / `--no-humanize` switch and seeded random generator (done)

- `DEFAULT_HUMANIZE = True`, `MidiOptions.humanize` and `seed: int = 0`,
  with `--humanize` / `--no-humanize` (`argparse.BooleanOptionalAction`)
  and `--seed N`.
- `conftest.convert` passes `humanize=False` by default (overridable through
  its `**options`), so existing end-to-end tests keep their exact
  expectations.
- `track_to_midi` creates a `random.Random` for each track, seeded from
  `(seed, track.id)` (e.g. via a string such as `f'{seed}:{track.id}'`, as
  `hash()` of a tuple differs between runs for strings). Tracks are then
  independent: converting one track or all of them gives the same file for
  that track.
- The generator can be injected for tests: `track_to_midi(track, score,
  output_path, options, rng=None)`. With `rng=None` it creates the seeded
  generator above. The generator stays out of `MidiOptions`: that is frozen
  settings data (the seed belongs there), while a generator changes state as
  it's used.
- Randomness rules, so a test stub stays small and seeded output stays
  reproducible: only `rng.randint` is used, and values are drawn in one
  fixed, documented order (see step 2).
- `conftest.py` gets `ScriptedRandom(values)`, a stand-in for
  `random.Random` whose `randint(a, b)` returns the given values in order.
  It asserts that each value is within `a … b` and fails clearly if more
  values are drawn than scripted. `convert` passes an `rng` argument through
  to `track_to_midi`.
- Nothing uses the generator yet, so the output doesn't change.
- Tests: `rng=None` with the same seed gives identical files; a
  `ScriptedRandom` is accepted (it isn't called yet).
- Done as planned. The seeding is `gp2midi.track_rng(track, options)`;
  tests are in `test_gp2midi_humanize.py`. Output with and without
  `--no-humanize` is byte-identical to before.

## Step 2: velocity randomisation (done)

- `DEFAULT_VELOCITY_SPREAD = 5`, `MidiOptions.velocity_spread`,
  `--velocity-spread N`.
- In pass 2, each onset tick gets one random offset,
  `rng.randint(-N, N)`. The offsets are stored in a dict keyed by tick and
  drawn the first time each tick is seen, in the order pass 2 visits the
  occurrences. That is the draw order the tests rely on: one draw per new
  struck onset tick, nothing else. Every note struck at that tick, on any
  string, voice or staff of the track, uses the same offset.
- The offset is added to the dynamic's base velocity in `note_velocity`
  (a new `offset` argument). The accent, ghost, hammer-on/pull-off, mute,
  grace and harmonic adjustments still apply per note on top, so an
  accented or ghost note in a chord still stands out from the others.
  The total is clamped to 1–127 as now.
- No offset with a fixed `--velocity`, and none for tied continuations
  (they aren't struck, so they don't draw a value).
- Tests (`test_gp2midi_humanize.py`) use `ScriptedRandom` for exact
  expected velocities. For example, offsets `[3, -5]` on two chords at MF give
  83 and 75 on every note. Cases: chord notes share one velocity; an accented
  note in a chord gets exactly `ACCENT_BOOST` more and a ghost note exactly
  `GHOST_CUT` less; a tied continuation draws no value; clamping at 1 and 127;
  `--velocity-spread 0`, a fixed `--velocity` and `--no-humanize` draw
  nothing and leave the output unchanged.
  Seeded runs (no stub): the same seed gives the same output, a different
  seed different output, and every value stays within ±N of the
  unrandomised one.
- End-to-end: a file with accents in chords and one with ghost notes in
  chords.
- Done as planned. Across all tracks of every file in `in/`, each onset
  tick has a single offset (comparing with the `--no-humanize` output,
  leaving out values clamped at 1 or 127), all offsets are within ±5, and
  chords with mixed velocities keep their differences (e.g. a rhythm
  guitar's 88 / 96 became 84 / 92). With `--no-humanize`, every file
  is byte-identical to before.
- Offsets are keyed by the written onset tick. A before-beat grace note has
  its own tick, so it gets its own offset, separate from its main note.

## Step 3: pick direction of each onset (done)

- `gpif`: `Beat.pick_stroke` (`'down'`, `'up'` or None) from the
  `PickStroke` property's `<Direction>`. Add fragment tests to
  `test_parsers.py`: down, up, absent, and a GP6-style beat.
- `gp2midi`: a standalone function `stroke_directions(onsets, ...)` that
  returns `'down'` or `'up'` for each picked onset tick, used between the two
  passes. It runs only for fretted (`track.is_fretted`), non-drum tracks.
  It walks the onsets in time order, merged over all voices and staves:
  1. If the beat has a pick stroke in the score, use it.
  2. Otherwise, if the onset is on the beat's picking grid, use its place
     on the grid. The picking hand keeps swinging down and up in time,
     through rests too. On the eighth-note grid, an onset on the beat is a
     downstroke and one on the 'and' an upstroke. A beat with an onset on
     a sixteenth between the eighths uses the sixteenth grid: the 1st and
     3rd sixteenths are down, the 2nd and 4th up. Beats are counted from
     the bar start (`bar_starts`), so an odd meter such as 7/8 doesn't
     shift the grid for later bars.
  3. Otherwise (off both grids, e.g. triplets or 32nds), if the onset is
     at most an eighth note (240 ticks) after the previous picked onset,
     use the opposite of the previous direction.
  4. Otherwise, use a downstroke.

  Single notes count as strokes too, so a run of eighth notes alternates
  down, up, down, up, and a quarter-note run is all downstrokes.

  Rule 2 replaced the first version's "alternate within an eighth, else
  down" rule (commit `cb6017e`) for onsets on the grid. That version made
  an offbeat eighth after a rest a downstroke, and so the next downbeat an
  upstroke (e.g. `4.3:D | 1.1:U` in a riff of offbeat eighths).
- These onsets aren't picked: tied continuations, hammer-on/pull-off
  destinations, legato-slide destinations and grace notes. They're left
  out, so they neither get a direction nor flip the next one. A grace
  note's main note is picked as usual.
- Each onset tick gets one direction. If the voices disagree (e.g. a
  scored stroke in one voice only), the scored one wins.
- Unit tests on the function alone: eighth notes, sixteenths, quarters,
  an offbeat eighth after a rest, offbeats only, a gallop (eighth and two
  sixteenths), the sixteenth grid applying to its own beat only, a dotted
  rhythm, beats counted from the bar start after 7/8, triplets falling back
  to alternation, an off-grid onset after a long gap, scored strokes, and
  hammer-ons that are skipped.
- The output doesn't change yet: nothing uses the directions until step 4.
- Done as planned, in two functions: `picked_onsets(occurrences, unpicked)`
  (tick → scored stroke or None, leaving out unpicked notes) and
  `stroke_directions(onsets, bar_starts)`. `track_to_midi` stores the
  result in `directions` for step 4. The grids and the eighth-note limit
  are constants (`EIGHTH_TICKS`, `SIXTEENTH_TICKS`,
  `ALTERNATE_PICK_TICKS`), not switches. Default and
  `--no-humanize` output are byte-identical to step 2's. To check the
  directions by hand, wrap `gp2midi.stroke_directions` to capture its
  result and run `track_to_midi` (no MIDI change to look at yet).
- Continuous triplets come out as D U D, D U D (each beat restarts on a
  downstroke, since the beat is on the grid) rather than the fully
  alternating D U D U D U many players use for fast triplets.
- Fingerstyle parts (e.g. arpeggiated acoustic or nylon parts) get pick
  directions too: the files don't say how a part is played. The instrument
  type (`track.instrument`, e.g. `nylonGuitar`) could be used to treat them
  differently later. See "Possible later additions".

## Step 4: strum spread for pick strokes (done)

- `DEFAULT_STRUM_TIME = 6` (ms), `MidiOptions.strum_time`, `--strum-time MS`.
- For each onset with more than one struck note, the first string struck is
  the lowest string on a downstroke and the highest on an upstroke. Each
  note's delay is `distance × strum_time`, where `distance` is the number of
  strings between it and the first string struck. Skipped strings count,
  since the pick crosses them too. GPIF string 0 is the lowest string. On a
  multi-staff track the strings are compared within a staff, though multi-
  staff tracks are rarely fretted.
- Milliseconds are converted to ticks with the occurrence's `bpm`:
  `ticks = ms × bpm × TICKS_PER_BEAT / 60000`.
- The delay is stored as an `offset` in the occurrence and applied only when
  emitting. Slide targets, the grace cut, the hammer-on/pull-off overlap and
  ties all still work on the written ticks.
- The note-on and the start of the pitch curve (bend, vibrato, slide) move
  later by the offset. The note-off stays at the written end, so a chord
  still ends together and never overlaps the next beat. The offset is
  capped below the note's sounding length.
- A string of a chord that is a tied continuation isn't struck, but it
  still counts towards the distances.
- With `--channel-per-string`, each delayed note's pitch-wheel events move
  with it on its own channel. Without it, the one curve for the chord's
  channel starts with its first note.
- Tests: down and up order, a skipped string, the tempo conversion, the
  note-off unchanged, a shift slide out of a strummed chord still gliding
  to its target, `--channel-per-string`, and `--strum-time 0` unchanged.
- End-to-end: a GP8 file and a `.gpx` file with picked chords. Check that chord
  onsets spread low to high and alternate on eighth-note runs.
- Done as planned. `strum_delays(occurrences, directions, unpicked, options)`
  gives each delayed note's ticks by occurrence index, with the
  `is_picked` filter shared with `picked_onsets` and `ms_to_ticks` for the
  conversion. The first string is the lowest (or highest) *struck* string:
  a tied string at the edge of a chord doesn't count, as nothing is struck
  there. Pitch events (curve and reset) move with the note only with
  `--channel-per-string`. On a shared channel they stay at the written
  tick, since a later plain note's reset would cut into a bent note's curve.
  A moved curve is squeezed to end at the written end.
- `conftest.convert` has a `strokes` argument (per-beat `pick_stroke`).
  The velocity tests' helper turns the strum off so they test velocity
  alone.
- Checked on the real files: note-offs are unchanged in every track
  compared, and `--no-humanize` is byte-identical to before. A GP8 file at
  72 BPM spreads up to 21 ticks, a `.gpx` file up to 22. A rhythm guitar
  playing eighth-note power chords alternates down (E then A) and up (A
  then E).

## Step 5: brush and arpeggio directions (done)

- `gpif`: `Beat.brush` from the `Brush` property's `<Direction>` and
  `Beat.arpeggio` from the `<Arpeggio>` element (`'down'` / `'up'` / None).
  Add fragment tests for both, in GP8 and GP6 (whitespace-indented) form.
- `gp2midi`: in `stroke_directions`, a brush or arpeggio sets the direction
  like a scored pick stroke (rule 1), so the alternation continues from it.
- The spread uses `--brush-time` (15 ms) or `--arpeggio-time` (40 ms) per
  string instead of `--strum-time`. Both are `DEFAULT_*` constants and
  `MidiOptions` fields.
- If one beat has more than one marking, arpeggio wins over brush and
  brush over pick stroke (the slowest spread).
- Tests: brush and arpeggio direction and spread, an up-brush followed
  within an eighth by an unmarked beat giving a downstroke, and the
  priority order.
- End-to-end: a `.gpx` file with arpeggios and a GP8 file with brushes.
- Done as planned. `gpif` parses `Beat.brush` and `Beat.arpeggio`.
  `gp2midi.beat_stroke(beat)` gives a beat's (direction, kind) by the
  priority above, and each occurrence carries `stroke` and `stroke_kind`
  (replacing `pick_stroke`). `strum_delays` uses the slowest kind among a
  chord's notes. A kind's time set to 0 turns off only that kind.
- Assumption: a marking's `Down` is a downstroke (low string first), as for
  pick strokes. This fits the data: 304 of 317 brushes and 39 of 40
  arpeggios are `Down`, and strums are mostly downstrokes. No reference
  confirms it.
- `conftest.convert`'s `strokes` argument became `beat_fields` (per-beat
  extra `Beat` fields, e.g. `{'brush': 'up'}`).
- Checked on the real files: `--no-humanize` is byte-identical to before,
  and the tracks that changed from step 4 are exactly those of files with
  brushes or arpeggios. Arpeggios at 90 BPM spread 29 ticks per string,
  and brushes about 8.

## Step 6: docs and listening pass (done)

- `docs/articulations.md`: move Brush, Arpeggio and pick stroke from
  "unhandled" to handled, with how they map to MIDI.
- CLAUDE.md: a **Humanize** entry under the key behaviours, the new test
  file, and the switches.
- Convert a few files with the defaults, listen, and adjust the `DEFAULT_*`
  values. Record the values chosen and why here.
- Docs done: `docs/articulations.md` (table rows for Brush, Arpeggio and
  Pick stroke, and implementation notes), `README.md` (what humanize does
  and its switches), CLAUDE.md (command example, planned-work entry). The
  **Humanize** key-behaviour entry and the test file were added in steps
  1–5.
- Listening: comparison files for a few songs at four settings can be made
  with the script below. Output goes to `tmp/listen/` (git-ignored).

  ```bash
  run() { local name=$1; shift; mkdir -p tmp/listen/$name
    for f in in/song1.gpx in/song2.gp in/song3.gp; do
      .venv/bin/python src/gp2midi.py "$f" -o tmp/listen/$name "$@" >/dev/null; done; }
  run 0-off --no-humanize
  run 1-subtle --velocity-spread 3 --strum-time 3 --brush-time 8 --arpeggio-time 25
  run 2-default
  run 3-strong --velocity-spread 10 --strum-time 12 --brush-time 25 --arpeggio-time 60
  ```

  Tracks worth comparing: arpeggios, brushes, alternating power chords,
  and picked chords at a slow tempo.
- Defaults chosen after listening (2026-10-15): the planned starting values
  are kept (±5, 6 / 15 / 40 ms). The preferred amount lies between
  `2-default` and `3-strong` and depends on the kind of track, so no one
  set of defaults fits better; adjust per conversion with the switches.
- Velocity variation applies to every converted track, including vocal,
  bass and drum tracks. The strum spread applies only to fretted tracks,
  including bass (rarely chords).

## Possible later additions

- Per-track humanize amounts, as the preferred spread and velocity variation
  depend on the kind of track (e.g. defaults chosen by `track.instrument`).
- Fingerstyle parts. A fingerpicking guitarist varies the timing within
  chords as an expressive technique, even within one piece, so neither a
  pick spread nor no spread is right throughout. Open question; the pick
  spread is good enough for now.

- Small random timing variation of each onset (not requested yet).
- A velocity variation within a strum (e.g. the last strings slightly
  softer on an upstroke).
- Confirm the `PickStroke` XML form against a real file.
