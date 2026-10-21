# Refactoring gpif.py into a general Guitar Pro library: status and plan

Started 2026-10-13. **Goal:** make `src/gpif.py` a general-purpose library
for reading Guitar Pro files (GP6/7/8, GPIF XML), so new scripts such as
`gpinfo.py` don't each repeat the loading and parsing code that
`gp2midi.py` uses. **Status:** all steps (1–6) done.

## Ground rules

- **MIDI output must not change.** A refactoring step must leave every
  `.mid` that `gp2midi.py` writes byte-identical, unless the step says
  otherwise. Before starting a step, take a baseline; after it, compare:

  ```bash
  rm -rf tmp/baseline tmp/after && mkdir -p tmp/baseline tmp/after
  for f in in/*.gp*; do .venv/bin/python src/gp2midi.py "$f" -o tmp/baseline --all-tracks >/dev/null; done
  # ... make the change ...
  for f in in/*.gp*; do .venv/bin/python src/gp2midi.py "$f" -o tmp/after --all-tracks >/dev/null; done
  diff -r tmp/baseline tmp/after && echo identical
  ```

  Also check `gpinfo.py` output with `.venv/bin/python src/gpinfo.py --json`.
- `.venv/bin/python -m pytest test` passes after every step.
- `gpif.py` (or its replacement) keeps no `mido` dependency.
- One step per commit. Update this file (the status table and that step's
  notes) and CLAUDE.md in the same commit.

## Status

| # | Step | Size | Status |
|---|---|---|---|
| 0 | Metadata additions for `gpinfo.py` | S | **Done** (4710c44) |
| 1 | `load_score(path)` returning all parsed sections | S | **Done** (725f652) |
| 2 | Explicit track → bar lookup (fixes a multi-staff bug) | S | **Done** (18198de) |
| 3 | Tracks with more than one staff | M | **Done** (1442d5a) |
| 4 | Split into a package (formats / parsing / theory) | M | **Done** (fa9fd02) |
| 5 | Typed objects instead of plain dicts | L | **Done** (2ecad1e) |
| 6 | Keep properties the parser doesn't handle | S | **Done** (2026-10-13) |

The order above is the suggested one: 1 and 2 are small and make the later
steps easier; 4 comes before 5 so the dataclasses go straight into their
final modules; 6 is independent and can go any time.

## Step 0: metadata additions (done)

Added for `src/gpinfo.py`, which lists fretted tracks with string count,
tuning and capo:

- `parse_tracks` returns `instrument` (GP8 `InstrumentSet/Type`, e.g.
  `electricGuitar`; GP6 `Instrument@ref`, e.g. `e-gtr6`; else None),
  `is_fretted` and `capo` (`CapoFret` staff property, default 0).
  `is_tab` is unchanged, so gp2midi's track selection is unaffected.
- Why `is_fretted`: GP8 gives vocal, flute, violin, piano and synth tracks a
  guitar `Tuning` property too, so `is_tab` isn't "fretted".
  `is_fretted_instrument()` matches guitar / bass / banjo / ukulele /
  mandolin names (GP8 types and GP6 refs) and excludes bassoon, contrabass
  and synths. A tab track with no instrument counts as fretted.
- `parse_score_info(root)`: the `<Score>` header (title, subtitle, artist,
  album, words, music, copyright, tabber, instructions, notices).
- `pitch_name(pitch)`: 60 → `C4`.
- `_find_first(el, *paths)`: first match of the GP8 path, then the GP6/7
  path; `parse_tracks` uses it for all its fallback lookups.

Open question: one sample file has a bass part with a bass tuning
(`<Tuning><Instrument>Bass`) but instrument type `leadSynthesizer`, so it is
not counted as fretted. Treating `Tuning/Instrument == 'Bass'` as fretted
would include it (`Guitar` there is useless: vocals have it too).

## Step 1: `load_score(path)` (done)

**Problem:** every consumer repeated `load_gpif_xml` plus eight `parse_*`
calls (`gp2midi.main`), and `track_to_midi` took those eight sections as
separate arguments.

**Done:**

- `gpif.Score`: frozen dataclass with `tracks`, `master_bars`, `bars`,
  `voices`, `beats`, `notes`, `rhythms`, `tempos`, `info` (from
  `parse_score_info`) and `root` (the XML, for anything not parsed yet).
  `info` and `root` default to `{}` / None so tests can build a Score by
  hand. The contents are still the existing dicts; step 5 types them.
- `gpif.parse_score(root)` runs every `parse_*` function;
  `gpif.load_score(path)` = `parse_score(load_gpif_xml(path))`.
  `load_gpif_xml` / `load_score` accept `str` or `Path`.
- `track_to_midi(track, score, output_path, options)`. It unpacks the
  sections into locals at the top, so the body is unchanged.
- `gp2midi.main`, `gpinfo.file_info` and `conftest.convert` use the new
  API. The `parse_*` functions stay public for fragment tests.
- Test: `test_load_score_matches_parse_functions` in `test_loading.py`.

**Checked:** 296 tests pass; all 126 `.mid` files from `in/` identical to
the baseline; `gpinfo.py --json` output identical. `gpinfo` now parses
the whole score, not just tracks and header: all of `in/` still takes
0.7 s.

## Step 2: explicit track → bar lookup (done)

**Problem:** `track_to_midi` found a track's bar as
`mb['bar_ids'][track['id']]`, assuming track ids are the positions 0, 1,
2… in `MasterBar/Bars`. That is wrong for tracks with more than one staff:
`MasterBar/Bars` holds one bar id **per staff**, not per track.

**Finding:** all files in `in/` have contiguous track ids 0…n-1, but one
GP8 file has 8 tracks with 11 staves (two string tracks, "Strings L" and
"Strings R", and a piano have two each), so every master bar lists 11 bar
ids. Before this step, tracks 4–7 of that file converted another track's
bars; e.g. the drum track played the organ's part on channel 9. All other files have one staff per track and were correct.

**Done:**

- `parse_tracks` returns `staff_count` (number of `Staves/Staff`, at least
  1; GP6/7 tracks have no `<Staves>` and count as 1; replaced by
  `len(track['staves'])` in step 3) and `bar_index` (the
  position of the track's first staff in `MasterBar/Bars`: the staff count
  of all tracks before it, in **document** order). Assumption: `Bars`
  follows `<Tracks>` document order. Guitar Pro writes tracks in id order,
  so the two orders agree in every file in `in/`.
- `gpif.track_bars(score, track, staff=0) -> list[dict | None]`: the
  staff's bar in each master bar (None where the id is missing, -1, or
  unknown). `IndexError` for a staff the track doesn't have.
- `track_to_midi` uses `track_bars(score, track)` (first staff only, as
  before). It no longer reads `score.bars` directly.
- Tests: `test_parse_tracks_bar_index_counts_staves_in_document_order`,
  `test_track_bars_*` (synthetic) in `test_parsers.py`;
  `test_real_multi_staff_file_track_bars` (that file) in `test_loading.py`.
  `conftest.TRACK` gained `bar_index: 0`, `staff_count: 1`.

**Checked:** 302 tests pass; `gpinfo.py --json` output identical. MIDI:
122 of 126 files identical; the 4 that differ are the intended fix, all
in that file:

| Track | Before (notes, pitch range) | After |
|---|---|---|
| 4 Strings R | 66, 56–81 (Strings L's 2nd staff) | 1195, 40–83 |
| 5 Organ | 1195, 40–83 (Strings R's 2nd staff) | 1754, 47–95 |
| 6 Piano | 0 (Strings R's 2nd staff, empty) | 264, 54–95 |
| 7 Drums | 1754, 47–95 (Organ) | 3332, 35–57 (drums) |

The baseline in `tmp/baseline` was regenerated after this step, so it
matches the corrected output for step 3 onwards.

## Step 3: tracks with more than one staff (done)

**Problem:** `parse_tracks` read tuning and capo from the first
`Staves/Staff` only, and gp2midi converted only the first staff's bars.
Data lost before this step (the multi-staff file from step 2):

- "Strings L": its first staff is empty and all its notes (66,
  pitches 56–81) are on the **second** staff, so its MIDI file was empty.
- Piano: the second staff (the left hand) was ignored.

**Done:**

- `parse_tracks` returns `staves`: `[{'tuning', 'capo'}, ...]`, one per
  staff (GP8 `Staves/Staff/Properties`, falling back to the track's
  `Properties` per property, as before; GP6/7: one staff from the track's
  `Properties`). `tuning` / `capo` stay as staff 0's. `staves` replaces
  step 2's `staff_count`; `track_bars` checks `len(track['staves'])`.
- `track_to_midi` merges every staff into the track's one MIDI file (what
  Guitar Pro plays back). Pass 1 walks bar by bar and, within a bar, staff
  by staff; each occurrence records its `staff`, and pitch / harmonic
  pitch use that staff's tuning. Single-staff tracks walk in the same order
  as before, so their output is unchanged.
- String state is keyed by `(staff, string)` (`string_key(occ)`), since
  each staff has its own strings: the grace-note cut, slide targets and
  hammer-on overlap no longer mix staves.
- `--channel-per-string` is off for multi-staff tracks (`string_channels`
  returns None): no fretted multi-staff track exists in `in/`, so channel
  allocation across staves wasn't worth designing. Revisit if one appears.
- Ties still key by `(channel, pitch)`, so a tie on one staff could extend
  the same pitch from the other staff. Harmless in practice (one channel
  can't hold two notes of one pitch anyway).
- `gpinfo.py` is unchanged: it shows staff 0's tuning. No fretted
  multi-staff tracks exist in `in/` to show otherwise.
- Tests: `test_parse_tracks_staves_have_their_own_tuning_and_capo`,
  `test_parse_tracks_gp8_staff_falls_back_to_track_properties`
  (`test_parsers.py`); new `test_gp2midi_staves.py` (both staves play with
  their own tuning, second staff alone, per-staff grace cut and slide
  target, channel-per-string off). `conftest.convert` gained
  `staff_of=[staff per beat]` and `track=`; `conftest.TRACK` has `staves`.
  The grace and slide tests fail if `string_key` ignores the staff.

**Checked:** 311 tests pass; `gpinfo.py --json` output identical. MIDI:
124 of 126 files identical to the step 2 baseline; the 2 that differ are
the intended change, both in that file:

| Track | Before (notes, pitch range) | After |
|---|---|---|
| 3 Strings L | 0 | 66, 56–81 |
| 6 Piano | 264, 54–95 (right hand) | 403, 23–100 (both hands) |

Both files have matched note-ons and note-offs. The piano has 7 places
where a note restarts a pitch that is already sounding; all 7 were already
in the first staff alone (the score doubles a pitch), none come from
merging. The baseline in `tmp/baseline` was regenerated after this step.

## Step 4: split into a package (done)

**Problem:** `gpif.py` mixed three concerns: container formats (zip, BCFZ,
BCFS), GPIF XML → data, and music theory (`midi_pitch`, harmonics,
`pitch_name`; `tuning_label` lived in `gpinfo.py`). Scripts found it only
because `src/` is on `sys.path`.

**Done:**

- **Package name `gpif`**, not the planned `gptab`: making `src/gpif/` a
  package with the old module's name keeps every `from gpif import ...`
  working unchanged, so the planned `gpif.py` shim (and deleting it later)
  wasn't needed. The name still fits: everything it reads is GPIF XML, in
  whichever container.
- Modules, split along the old file's section markers (`git mv` to
  `parse.py`, so history follows the largest piece):
  - `container.py`: `load_gpif_xml`, `_bcfz_decompress`, `_bcfs_files`.
  - `parse.py`: `parse_*`, `bend_points`, `is_fretted_instrument`,
    `_parse_staff`, `_find_first`, `TICKS_PER_BEAT`, `NOTE_VALUE_BEATS`,
    `SLIDE_*`, `ACCENT_*`, `HARMONIC_TYPES`.
  - `score.py`: `Score`, `parse_score`, `load_score`, `track_bars`.
  - `theory.py`: `pitch_name`, `midi_pitch`, `harmonic_interval`,
    `harmonic_pitch`, and `tuning_label` (+ `STANDARD_GUITAR`,
    `STANDARD_BASS`, `FLAT_NAMES`) moved from `gpinfo.py`.
  - `__init__.py`: re-exports the public API, listed in `__all__`.
    Underscore names stay private to their module.
- `pyproject.toml` (setuptools, `src/` layout) packages `gpif` only, with
  no dependencies, Python ≥ 3.10 (the dataclass annotations use `X | None`
  at run time). The scripts don't need it: they still import `gpif` from
  their own directory, so `conftest.py`'s path setup is unchanged.
  `.gitignore` gained `build/` and `*.egg-info/` (left by `pip install .`).
- Tests now mirror the modules: `test_theory.py` (pitch / harmonic tests
  from `test_parsers.py`, `tuning_label` tests from `test_gpinfo.py`),
  `test_score.py` (`track_bars` tests from `test_parsers.py`);
  `test_loading.py` imports the private container helpers from
  `gpif.container`. Same 311 tests, none changed beyond imports (and
  `test_theory.py` merges two identical standard-tuning constants).
- Docs: CLAUDE.md (architecture, test list, install command),
  `docs/articulations.md` (parsing location).

**Checked:** 311 tests pass; pyflakes clean on `src/` and `test/`; all 126
`.mid` files identical to the step 3 baseline; `gpinfo.py --json` output
identical; `gpinfo.py` runs from another working directory. `pip install
.` into a fresh venv works, and from there `import gpif` resolves every
name in `__all__` and loads a `.gpx`.

## Step 5: typed objects instead of plain dicts (done)

**Problem:** parsed data was dicts with string keys. Typos failed at run
time, fields weren't discoverable, and test fixtures (`conftest.TRACK`,
`test_gp2midi_channels.py`, `test_gp2midi_grace.py`) silently lacked new
fields such as `capo` (steps 2 and 3 had to add `bar_index` / `staves`
to hand-built track dicts by hand).

**Done:**

- New `gpif/model.py` (not `parse.py`: the types are what callers use,
  the parsers are how they're built) with frozen dataclasses `Track`,
  `Staff`, `MasterBar`, `Bar`, `Voice`, `Beat`, `Note`, `Harmonic` (was
  the `{'type', 'fret'}` dict), `Rhythm`, `Tempo`, `ScoreInfo` (was the
  `info` dict), all exported from `__init__.py`. `model.py` imports
  nothing, so every other module can use it.
- **Defaults on every field except ids and `Rhythm`'s** (whose `ticks`
  default would duplicate `TICKS_PER_BEAT`): tests build `Note(fret=5)` or
  `Track(id=0, staves=[...])` and vary them with `dataclasses.replace`.
- **`Track.tuning` / `Track.capo` are properties** reading `staves[0]`,
  removing the duplicate fields step 3 kept for compatibility.
- **Lists stay lists** (`tuning`, `bar_ids`, `note_ids`, `bend`, ...):
  frozen stops reassigning a field, not mutating a list, but tuples would
  have changed every `== [..]` assertion and gpinfo's JSON for no gain
  here. Objects holding lists aren't hashable; nothing hashes them.
- Container dicts stay: `Score.notes` etc. are still `dict[int, Note]`
  keyed by GPIF id. gp2midi's pass-1 occurrence dicts are internal and
  unchanged. `gpinfo`'s JSON rows are still dicts (they are output).
- Done in three stages, each with tests + the byte-identical MIDI check:
  (A) `ScoreInfo`, `MasterBar`, `Bar`, `Voice`, `Rhythm`, `Tempo`;
  (B) `Track`, `Staff`; (C) `Beat`, `Note`, `Harmonic`.
- `theory.harmonic_pitch` takes a `Note` (imports `model`).
- Tests: `conftest.convert` still takes note-override **dicts** (most
  tests pass `{'fret': 5, ...}`) and builds `Note(**{'string': 2, 'fret':
  7, **n})`; `conftest.TRACK` is a `Track`. Per-file `PLAIN` / `BASE`
  note dicts became `Note()`, `{**PLAIN, 'k': v}` became
  `replace(PLAIN, k=v)`. Full-note dict literals in the parser tests
  became `Note(string=.., fret=.., midi=..)` (still checks every other
  field is its default). The drum-grace test's `monkeypatch.setitem` on
  `TRACK` became a `track=` argument; its `tuning` patch had been a no-op
  since step 3 (gp2midi reads the staff's tuning), now it really clears it.
- Fixed the README library example from step 4, which used dict access.

**Checked:** 311 tests pass; pyflakes clean; all 126 `.mid` files
identical to the step 3 baseline; `gpinfo.py --json` output identical;
README example runs. Cost: `parse_score` over all of `in/` takes 0.23 s
instead of 0.17 s (frozen dataclass construction is slower than a dict
literal); 60 ms over 19 files is negligible next to loading them, so no
`slots` or other tuning.

## Step 6: keep properties the parser doesn't handle (done)

**Problem:** `parse_notes` and `parse_beats` dropped anything they didn't
recognise (e.g. `LetRing`, `Brush`, whammy, see `docs/articulations.md`),
so a script needing one had to re-walk the XML.

**Finding:** a survey of `in/` shows the unparsed data comes in two
shapes. Simple `<Property>` values (Beat `Brush` → `Down`, `Slapped` flag,
`PrimaryPickupVolume` → `0.5`, Note `ConcertPitch`, ...), and structured
child elements: `<LetRing/>` (326 notes), `<Whammy originValue=...
middleValue=...>` (attributes, 31 beats), `<Lyrics><Line>` (nested),
`<Arpeggio>`, `<Wah>`, `<Fadding>`, `<Chord>`, `<FreeText>`, ... A flat
`extra: dict[str, str]` alone would lose the attributes and nesting, so
both planned options were done:

- **`element`** on every model object built from an XML element (`Track`,
  `Staff`, `MasterBar`, `Bar`, `Voice`, `Beat`, `Note`, `Rhythm`, `Tempo`,
  `ScoreInfo`): the source `ET.Element`, lossless and free (the tree is
  held by `Score.root` anyway). None when built by hand, for a GP6
  `Staff` (its properties are on the track: `Track.element`), and for the
  `<Score>` tempo fallback. `Harmonic` (built from two properties) has
  none.
- **`properties`** on `Note` and `Beat`: every `<Property>` name →
  `property_value` text (first child's text; '' for flags like `<Enable/>`
  and for structured values like `<Pitch>`). All properties, not just
  unhandled ones, so there's no list of handled names to keep in sync.
- `element` is excluded from `==` and `repr`; `properties` isn't a field
  at all. Equality still means "same parsed meaning", so no existing test
  changed.
- `property_value` is public (exported from `gpif`), for reading
  properties on other elements (e.g. a `Staff.element`).

**Performance:** baseline `parse_score` 0.098 s on the largest file
(13,950 notes), 0.203 s for all of `in/`. A first version stored
`properties` as an eagerly built dict field: 0.144 s (+47%); building it
inside `parse_notes`' existing property loop and a leaner
`property_value` brought that to 0.126 s. Final version:
`properties` is a `functools.cached_property` computed from `element` on
first use (works on frozen dataclasses: it writes the instance `__dict__`
directly), so parsing doesn't build it: **0.104 s** (+6%, from setting
`element`), 0.219 s for all of `in/`. `property_value` therefore lives in
`model.py` (`parse.py` imports `model`, not the other way round).

**Tests:** new `test_model.py` (`property_value` cases, lazy and cached
`properties`, `{}` without an element, raw fields out of `==` / `repr`,
still frozen); `test_parsers.py`: every parser keeps its element, tempo
fallback has none, beat properties; `test_loading.py`: real files, let
ring (GP8 and GP6), brush direction and whammy attributes read through
`element` / `properties`.

**Checked:** 323 tests pass; pyflakes clean; all 126 `.mid` files and
`gpinfo.py --json` output identical.

## Possible next steps

Not planned; candidates noticed along the way:

- Parse let ring, brush strokes and whammy bar into typed fields and use
  them in gp2midi (see `docs/articulations.md`).
- Recognise `Tuning/Instrument == 'Bass'` as fretted (the open question
  under step 0).
- `--channel-per-string` for multi-staff fretted tracks (step 3), if one
  turns up.
