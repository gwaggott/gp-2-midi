# Reading GP3 / GP4 / GP5 files: plan and status

Started 2026-10-20 on branch `gp345`. **Goal:** `gp2midi.py` and
`gpinfo.py` accept `.gp3`, `.gp4` and `.gp5` files (Guitar Pro 3–5's
binary format) as well as the GPIF formats they read now (`.gp`, `.gpx`,
raw `.gpif`). Each file format gets its own reader class. What the
readers have in common comes from mixins. **Status:** all steps (0–7)
done; merged into `main` on 2026-10-20 after the user checked
`out/gp345/`.

## Ground rules

These are the same as `docs/refactoring.md`:

- **GPIF output must not change.** Every `.mid` that `gp2midi.py` writes
  from `in/` stays byte-identical unless a step says otherwise. Take a
  baseline before each step and compare after it:

  ```bash
  rm -rf tmp/baseline tmp/after && mkdir -p tmp/baseline tmp/after
  for f in in/*.gp in/*.gpx; do .venv/bin/python src/gp2midi.py "$f" -o tmp/baseline --all-tracks >/dev/null; done
  # ... make the change ...
  for f in in/*.gp in/*.gpx; do .venv/bin/python src/gp2midi.py "$f" -o tmp/after --all-tracks >/dev/null; done
  diff -r tmp/baseline tmp/after && echo identical
  ```

  Also compare `.venv/bin/python src/gpinfo.py --json` before and after.
- `.venv/bin/python -m pytest test` passes after every step.
- The `gpif` package stays usable with no dependencies for GPIF files.
  PyGuitarPro is only imported when a GP3–5 file is read (see decision 1).
- One step per commit. Each commit updates this file (the status table
  and that step's notes) and `CLAUDE.md`.

## Status

| # | Step | Size | Status |
|---|---|---|---|
| 0 | This plan, branch `gp345` | S | **Done** (2026-10-20) |
| 1 | Reader classes for the existing GPIF formats (pure refactor) | M | **Done** (2026-10-20) |
| 2 | Shared helpers as mixins, used by the GPIF readers | M | **Done** (2026-10-20) |
| 3 | GP3 / GP4 / GP5 readers: structure, rhythm, pitch, dynamics, tempo | L | **Done** (2026-10-20) |
| 4 | GP3–5 articulations: flags (accent, ghost, staccato, palm mute, dead, vibrato, slides) | M | **Done** (2026-10-20) |
| 5 | GP3–5 articulations: hammer-on/pull-off, bends, harmonics, grace notes, strokes | L | **Done** (2026-10-20) |
| 6 | Cross-format check and real files in `in/` | M | **Done** (2026-10-20) |
| 7 | Docs, packaging, `gpinfo`, merge | S | **Done** (2026-10-20) |

Steps 1 and 2 are pure refactors, so they can be checked byte for byte
before any new format arrives. Step 3 produces usable MIDI from GP3–5
files without articulations. Steps 4 and 5 add articulations in two
batches: the simple flags first, then the ones that need logic across
notes. Step 6 is the end-to-end check.

## PyGuitarPro: findings

The library was installed in a scratch venv; it isn't a project
dependency yet.

- **Version and scope:** `pyguitarpro` 0.11 on PyPI. It reads and writes
  GP3, GP4 and GP5 only, so there's no GPX or GP7/8 support to overlap
  with ours. It supports Python 3.10–3.14 and its only dependency is
  `attrs`.
- **Licence:** LGPL-3.0-only. Using it as an installed library (import,
  unmodified) puts no licence requirement on this project. Copying or
  modifying its source would make those files LGPL. This repo has no
  licence file.
- **API:** `guitarpro.parse(path) -> Song`. It detects the version from
  the file header: a length-prefixed string at byte 0, `FICHIER GUITAR
  PRO v3.00`, `v4.06`, `v5.00`, `v5.10` (and `CLIPBOARD` variants). The
  model is attrs classes:
  - `Song`: title, artist, album, words, music, copyright, tab,
    instructions, notice, tempo, `measureHeaders`, `tracks`.
  - `MeasureHeader`: time signature, `start` in ticks (960 per quarter),
    and repeats, markers and key.
  - `Track`: `strings` (`GuitarString(number, value)`, number 1 = the
    **highest** string, value = MIDI pitch), `offset` (capo),
    `channel.channel` / `.instrument` (MIDI program), `isPercussionTrack`,
    and `measures`.
  - `Measure` → `voices` (2 in GP5, 1 in GP3/4) → `Beat`. A beat has a
    `duration` (value, dots, tuplet), `start`, `status` (empty / normal /
    rest), `notes` and an `effect`: stroke, pick stroke, tremolo bar, beat
    vibrato, `mixTableChange` (tempo and more).
  - `Note`: `value` (fret), `string`, `velocity`, `type` (normal / tie /
    dead / rest) and an `effect`: accent, heavy accent, ghost, staccato,
    palm mute, let ring, hammer, vibrato, slides, bend, harmonic, grace,
    trill, tremolo picking.
- **Round trip:** a test song written with `guitarpro.write` as GP3, GP4
  and GP5 reads back identically, except that GP3 drops palm muting (the
  format has no field for it). So unit tests can build songs in code and
  write them to `tmp_path` in every version, with no binary test files.
- **Bend units:** `BendPoint.value` is in **quarter tones** (GP's 25
  units), although PyGuitarPro names its scale `semitoneLength = 1`.
  Semitones = value / 2. In the local files, 4 (a full bend) is the most
  common value, then 2 (half), then 1 (quarter). Positions are 0–12 along
  the note (the file's 0–60, rounded).
- **Survey of 32 real GP3–5 files** (6 × v5.00, 14 × v5.10,
  7 × v4.06, 4 × v4.00, 1 × v3.00): all parse, in 1.65 s total. Over
  188,448 notes in 207 tracks (35 drum; 4-, 5-, 6- and 7-string):
  - tie 11,911, dead 3,216
  - let ring 8,933 (not used by gp2midi for GPIF either)
  - palm mute 4,911, hammer 2,798, staccato 2,603, ghost 1,978
  - vibrato 1,324 (plus 17 beat vibratos), bend 1,110, accent 1,053
    (heavy 46)
  - slides: legato 1,260, shift 440, out down 319, out up 26, in from
    below 64, in from above 7
  - grace notes: 436 before the beat, 23 on it
  - harmonics: 103 natural, 33 artificial, 18 semi, 6 tapped, 1 pinch
  - strokes: down 75, up 10, pick stroke 60, rasgueado 5
  - tremolo picking 104, whammy bar 63 (neither used for GPIF)
  - tuplets: 2,148 triplets, plus 5:4, 6:4, 7:4 and 9:8; 3,564 dotted
    beats
  - 57 tempo changes, 9 of them mid-bar
  - No second-voice notes in these files.
  - Velocities are the GP dynamic levels (15, 31, … 127; 95 = f is the
    default). In 3,834 beats the notes don't all have the same velocity.

## Design

### Reader classes and mixins

```
gpif/readers/
  base.py        ScoreReader: name, extensions, sniff(head: bytes) -> bool,
                 read(path) -> Score
  containers.py  ZipContainerMixin       .gp (and zip .gpx): Content/score.gpif
                 BcfsContainerMixin      GP6 .gpx: BCFZ / BCFS → score.gpif
                 RawXmlContainerMixin    .gpif / .xml
                   each provides sniff() and load_xml(path) -> ET.Element
  gpif_xml.py    GpifContentMixin        XML root → Score (today's parse_* functions)
                 Gp7Reader(ZipContainerMixin, GpifContentMixin, ScoreReader)
                 Gp6Reader(BcfsContainerMixin, GpifContentMixin, ScoreReader)
                 GpifXmlReader(RawXmlContainerMixin, GpifContentMixin, ScoreReader)
  registry.py    READERS (sniff order), reader_for(path), load_score(path),
                 load_gpif_xml(path)
  gp345.py       PyGuitarProMixin        guitarpro.Song → Score
                 Gp3Reader / Gp4Reader / Gp5Reader(_GpHeaderSniffMixin,
                                         PyGuitarProMixin, ScoreReader)
  mixins.py      shared by every format's content mixin (step 2):
                 TrackClassificationMixin  classify_track(tuning, channel, instrument)
                                         → (is_drum, is_tab, is_fretted)
                 RhythmMixin             rhythm(beats, dots, tuplet) → Rhythm
                 PitchEffectsMixin       bend_curve(points, position_scale,
                                         semitone_scale) → [(fraction, semitones)];
                                         harmonic(type, fret) → Harmonic | None
                 DynamicsMixin           velocity → PPP … FFF (step 3)
                 ScoreBuilder            (step 3; a class, not a mixin) hands out
                                         ids and collects bars, voices, beats,
                                         notes and rhythms into a Score
```

Before step 2, the GPIF parsing was the module functions in
`gpif/parse.py`. It is now the methods of `GpifContentMixin`, so it can
inherit the shared mixins. The old functions still exist, as methods bound
to one parser instance.

- **Containers and content are separate mixins.** The GPIF readers differ
  only in how they get the XML, and all three parse it the same way. A
  reader class is then one line combining a container mixin and a content
  mixin. A new container (e.g. a GP7 file inside another archive) is one
  new mixin.
- **GP3, GP4 and GP5 get a class each,** although PyGuitarPro hides most
  version differences, so these classes will be thin. They still sniff
  their own header and note what each version can't express (GP3 has no
  palm mute, and no second voice before GP5). If one version needs a
  workaround later, it has a place to go.
- **Sniffing, not extensions:** `reader_for` asks each reader's `sniff`
  about the file's first bytes, in the order zip, BCFZ/BCFS, GP3–5 header,
  XML. That is what `load_gpif_xml` does now with magic bytes. Extensions
  are only used in error messages and the CLI's help.
- **The public API stays.** `gpif.load_score(path)` and `parse_score(root)`
  keep their meaning, and so do `load_gpif_xml` and every `parse_*`
  function, which the fragment tests use. Readers are added to `__all__`
  for callers that want a specific one.
- **The model doesn't change shape.** GP3–5 data goes into the same
  `Score` / `Track` / `MasterBar` / `Bar` / `Voice` / `Beat` / `Note`
  objects, with generated ids. `gp2midi` and `gpinfo` only use the model
  (they never read `element`, `properties` or `Score.root`), so they need
  no format-specific code.

### Mapping GP3–5 to the model

| Model | From PyGuitarPro |
|---|---|
| `Score.info` | `Song` title, subtitle, artist, album, words, music, copyright, tab (→ `tabber`), instructions, notice (joined) |
| `Track` | `name`; `program` = `channel.instrument`; `channel` = `channel.channel` (9 if `isPercussionTrack`); one `Staff` with `tuning` = string values reversed (lowest first) and `capo` = `offset`; `bar_index` = track position |
| `MasterBar` | one per `MeasureHeader`: time signature, `bar_ids` (one per track) |
| `Bar`, `Voice` | per `Measure` / `Voice`; voices with no beats are left out |
| `Beat` | `rhythm_id` from `duration`; `is_rest` from `status`; `dynamic` from the note velocities; strokes from `effect.stroke` / `pickStroke` |
| `Rhythm` | 960-tick `Duration.time` → beats; dots and tuplets as in `parse_rhythms` |
| `Note` | `string` = string count − `string` (0 = lowest); `fret` = `value`; `midi` = None (gp2midi uses tuning + fret); `is_tie_dest` = `type == tie`; `dead` = `type == dead` |
| `Tempo` | `Song.tempo` at bar 0, then each beat's `mixTableChange.tempo` at its bar and position |
| `element` / `properties` | None / `{}`; the `Song` is kept on the `Score` instead (decision 5) |

Articulations (steps 4 and 5):

| Model | From PyGuitarPro | Notes |
|---|---|---|
| `accent` | `accentuatedNote` → normal, `heavyAccentuatedNote` → heavy | |
| `ghost`, `staccato`, `palm_muted` | same-named flags | |
| `vibrato` | note `vibrato` → slight; beat `effect.vibrato` → wide on its notes | Check against GP8's own conversion in step 6 |
| `slide_in` / `slide_out` | `intoFromBelow` / `intoFromAbove`; `shiftSlideTo` → shift, `legatoSlideTo` → legato, `outDownwards` / `outUpwards` | A note can have one of each |
| `hopo_origin` / `hopo_dest` | `hammer` marks the note the slur starts from; the next note on the same string is the destination | To confirm with a file that has both formats (step 6) |
| `bend` | points → `(position / 12, value / 2)` | Quarter-tone units, see findings |
| `harmonic` | natural / pinch / semi / tapped / artificial → `HARMONIC_TYPES` | Natural: node = fret. Tapped: node = tapped fret − fretted fret. Artificial: an octave enum, mapped to a node (12 = octave, 19 = octave + fifth, 24 = two octaves). |
| grace beat | `effect.grace` on the main note becomes a grace `Beat` (before / on beat) with its own note (`fret`, `isDead`) and a 32nd-note rhythm | Grace notes are beats in our model but note effects in GP3–5 |
| `brush` / `pick_stroke` | `stroke.direction` / `pickStroke` | GP3–5 has no arpeggio marking. Rasgueado is ignored. |

## Decisions to make

These started as recommendations. Each is decided in the step that
needs it, and the decision is recorded here. Decisions 1, 2, 4 and 5 were
taken as recommended in step 3. Decision 3 is still open.

1. **Dependency:** make `pyguitarpro` an optional extra of the `gpif`
   package (`pip install gpif[gp5]`) and import it lazily in
   `readers/guitarpro.py`. Reading a GP3–5 file without it gives a clear
   error. `requirements.txt` pins it (`pyguitarpro==0.11`) so the scripts
   always have it. **Done in step 3**: the extra is `gp5 =
   ["pyguitarpro>=0.11"]`, and the module is `readers/gp345.py`.
2. **Per-note dynamics:** 3,834 beats in the local files mix velocities,
   which `Beat.dynamic` can't hold. The recommendation is to add an
   optional `Note.dynamic`, None = use the beat's. `note_velocity` would
   use it, and GPIF notes would always have None, so GPIF output doesn't
   change. The cheaper option is the most common velocity per beat. Only
   452 of the 3,834 beats have an accent or ghost flag, and 180 more have
   a tie, so most are genuinely different dynamics. They're spread across
   files: the three with the most have 479, 417 and 398. **Done in step 3:** every GP3–5 note gets `Note.dynamic`,
   and the beat gets the most common one. gp2midi uses `note.dynamic or
   beat.dynamic`.
3. **Mid-bar tempo changes:** gp2midi applies only tempo changes at bar
   position 0. That already drops 21 changes in the GPIF files in `in/`,
   and it would drop 9 of 57 in the GP3–5 files. Fixing it changes GPIF
   output, so it's a separate step after this plan if wanted. **Found
   in step 3:** gp2midi's tempo loop only moves past a change at position
   0, so a mid-bar change also blocks every later change in the track's
   file. In one sample file a change at bar 5, position 0.125, means none
   of its later tempo changes are applied. The GP3–5 reader keeps mid-bar
   changes in `Score.tempos`, the same as GPIF, so the same applies there.
   **Decision (2026-10-20): not fixed for now.** The user isn't unduly
   concerned, so it stays a known bug, noted in `CLAUDE.md` (Tempo) and
   the README's known issues. Step 6 found the effect on that file: its
   `.gp` MIDI stays at 76 BPM after bar 5.
4. **Track classification without instrument names:** GP3–5 tracks only
   have a MIDI program. Set `instrument` from the General MIDI program
   family (24–31 guitar, 32–39 bass, else the GM name), so that
   `is_fretted_instrument` keeps working and vocal or keyboard tracks
   aren't counted as fretted. **Done in step 3** (`gm_instrument`): the
   guitar, bass and banjo programs are named (`Distortion Guitar`,
   `Electric Bass (finger)`, `Banjo`, …), and other programs get their
   family (`Piano`, `Ensemble`, `Synth Lead`, …). Synth basses (38, 39)
   aren't fretted, as for GPIF. A program says what the track sounds
   like, not what it is: one file's "Glockenspiel" track uses an
   electric guitar program, so it counts as fretted.
5. **Raw access:** GPIF objects keep their XML in `element`. GP3–5
   objects would have `element = None`. Add `Score.source` (the
   `guitarpro.Song`) for anything not converted, rather than overloading
   `root`. **Done in step 3:** `Score.source` is excluded from `==` and
   `repr`.
6. **Package name:** `gpif` will also read non-GPIF files. Renaming it
   would break every import, so keep the name and change the
   `pyproject.toml` description.

## Out of scope

These aren't handled for GPIF either: repeats (bars are played once, as
written), let ring, tremolo picking, trill, and the whammy bar. They're
noted in `docs/articulations.md`.

## Test files

- **Unit tests:** songs built in code and written with `guitarpro.write`
  to `tmp_path` as GP3, GP4 and GP5. There are no binary fixtures, and
  every feature can be tested in every version.
- **Real files:** 32 GP3–5 tabs from the user's own collection were
  copied into `in/` (1 × GP3, 11 × GP4, 20 × GP5; 2 MB), renamed to the
  folder's lowercase, underscore style. They are for end-to-end checks and
  surveys only: **unit tests don't read them**, so the tests don't depend
  on third-party tabs. `test_all_input_files_load` loads every file in
  `in/`, GP3–5 ones included, as a local check, and skips when `in/` has
  none. Like everything in `in/`, they're git-ignored
  (possibly copyrighted), so they exist only in this checkout.
- **Cross-format check (step 6):** export one or two of the GPIF songs in
  `in/` from Guitar Pro 8 as `.gp5`. Then convert both with gp2midi and
  compare notes, pitch bends and velocities. This is the best check of
  the hammer-on, vibrato and harmonic mappings above.

## Step notes

### Step 0: plan (done)

Branch `gp345` from `main` at `f3e83a7`. PyGuitarPro was investigated in
a scratch venv (findings above), and nothing in the project uses it yet.

### Step 1: reader classes for the GPIF formats (done)

**Done:**

- New package `gpif/readers/`, laid out as in the design above:
  - `ScoreReader` base class.
  - Three container mixins. They were made from `load_gpif_xml`'s three
    branches, with the same checks and error messages.
  - `GpifContentMixin`, which reads with `parse_score`.
  - `Gp7Reader`, `Gp6Reader` and `GpifXmlReader`.
  - The registry.
- `gpif/container.py` was moved (`git mv`) to `readers/containers.py`,
  where the BCFZ / BCFS codecs stay private.
- The GPIF module is `gpif_xml.py`, not the planned `gpif.py`, so it
  doesn't share the package's name. The GP6 mixin is `BcfsContainerMixin`
  (BCFS is the container; BCFZ is its compressed form).
- `load_score` moved from `score.py` to the registry and now picks a
  reader. `score.py` keeps `Score`, `parse_score` and `track_bars`
  (`parse_score` moved in step 2).
- `load_gpif_xml` keeps its behaviour. It asks the registry and raises
  `ValueError` for a reader without GPIF XML, which will be the GP3–5
  readers.
- `reader_for` reads the first 64 bytes (`HEAD_BYTES`, enough for the
  GP3–5 header) and tries each reader's `sniff` in `READERS` order. The
  raw XML mixin accepts anything, so it is last, as the old
  `load_gpif_xml` fell through to XML.
- The readers, `reader_for`, `load_gpif_xml` and `load_score` are
  exported from `gpif`.
- `pyproject.toml` packages `gpif.readers` too.
- Tests in `test_loading.py`:
  - format detection by content, also with a misleading suffix;
  - each reader reads a synthetic file;
  - no matching reader;
  - a stand-in non-GPIF reader through `load_score` and `load_gpif_xml`;
  - the abstract base;
  - the real `.gp` / `.gpx` files picking their readers.
  The private codec imports now come from `gpif.readers.containers`.

**Checked:**

- 425 tests pass and pyflakes is clean.
- All 126 `.mid` files (`--all-tracks`, every `.gp` / `.gpx` in `in/`)
  and the `gpinfo.py --json` output are identical to the step 0 commit,
  which was run from a git worktree.
- `pip install .` into a fresh venv works: every name in `__all__`
  resolves, and a `.gpx` loads through `Gp6Reader`.

### Step 2: shared helpers as mixins (done)

**Done:**

- `gpif/parse.py` moved (`git mv`) into `readers/gpif_xml.py`. Its
  functions became methods of `GpifContentMixin`: `parse_score`, one
  `parse_*` per section, `parse_staff` (was `_parse_staff`) and
  `bend_points`. The step 1 reader classes are in the same module. The
  GPIF-only constants (`NOTE_VALUE_BEATS`, `SLIDE_*`, `ACCENT_*`,
  `SCORE_FIELDS`) and helpers (`_find_first`, `_direction`) stay there.
- `parse_score` moved there from `score.py`, which now holds only `Score`
  and `track_bars`. That also removes `score.py`'s import of the parser,
  which would otherwise be an import cycle.
- New `readers/mixins.py`, holding only what a second format will
  actually share:
  - `TrackClassificationMixin.classify_track`: the drum / tab / fretted
    rule, plus `is_fretted_instrument` and its patterns.
  - `RhythmMixin.rhythm`: note value, dot and tuplet → `Rhythm`, plus
    `TICKS_PER_BEAT`.
  - `PitchEffectsMixin.bend_curve`: points in a format's own units →
    `[(fraction, semitones)]`, stable-sorted (GPIF: offsets / 100, values
    / 50; GP3–5 will use positions / 12, quarter tones / 2).
  - `PitchEffectsMixin.harmonic`: type and fret → `Harmonic` or None,
    plus `HARMONIC_TYPES`.
  They are static methods, so they hold no state, and a format can
  override one (tested).
- The `ScoreBuilderMixin` and `DynamicsMixin` planned for this step move
  to step 3. GPIF has its own ids and dynamic names, so nothing here would
  use them yet.
- The public API is unchanged: every `gpif.parse_*`, `gpif.bend_points`
  and constant is still exported. The `parse_*` functions are the bound
  methods of one module-level `GpifContentMixin()`. The mixins are
  exported too. Nothing outside the package imported `gpif.parse` or
  `gpif.score` directly.
- The arithmetic is unchanged, so floats match: the dot × 1.5 comes before
  the tuplet × den / num, and the bend sort is stable on position.
- Tests: new `test/test_mixins.py` covers each mixin, the composition, and
  a parser subclass overriding `classify_track`.

**Checked:**

- 442 tests pass and pyflakes is clean.
- All 126 `.mid` files and the `gpinfo.py --json` output are identical to
  the step 1 commit, which was run from a worktree.
- `parse_score` over the 19 GPIF files takes 0.271 s, against 0.269 s
  before (best of 5).

### Step 3: GP3 / GP4 / GP5 readers (done)

**Done:**

- `readers/gp345.py`:
  - `PyGuitarProMixin` (all four shared mixins) converts a
    `guitarpro.Song`, using `convert_song`, `convert_info`,
    `convert_track`, `convert_measure`, `convert_beat`, `convert_note`
    and `convert_tempos`.
  - `Gp3Reader`, `Gp4Reader` and `Gp5Reader` are registered before the
    raw XML fallback. They sniff the `FICHIER GUITAR PRO v3` / `v4` /
    `v5` header.
  - The module is named `gp345.py`, not the planned `guitarpro.py`, so it
    can't be mistaken for the library.
- Shared code added in `mixins.py`:
  - `DynamicsMixin.dynamic_for_velocity`: the nearest of 15, 31, … 127,
    the softer on a tie, plus `DYNAMICS`.
  - `ScoreBuilder`: ids from 0 per kind, and equal rhythms share an id.
  - The planned `ScoreBuilderMixin` became a class. Readers are single
    shared instances, so per-file state can't live on them; each `read`
    makes its own builder.
- Model:
  - `Note.dynamic` (decision 2);
  - `Score.source` (decision 5);
  - gp2midi uses `note.dynamic or beat.dynamic`.
- Mapping as in the tables above:
  - Strings are mirrored (GP string 1 = the highest), and the tuning is
    sorted lowest first.
  - A voice whose beats are all empty is left out. Every GP5 measure has
    a second voice, usually one empty beat, and a bar where a track is
    silent has only empty beats. An empty beat inside a used voice is a
    rest.
  - Tempo changes on any track count, at (bar, beat start / bar length).
    The first one found at a place wins, and a change at the very start
    replaces the song tempo.
- Packaging: the `gp5` extra, the pin in `requirements.txt` and the
  description. README and CLAUDE.md are updated.
- Tests: new `test/test_gp345.py`, parametrized over GP3, GP4 and GP5
  where the format allows. It covers:
  - detection, also with a misleading suffix;
  - `load_gpif_xml` refusing a GP5 file;
  - the missing-library error;
  - info, tracks (tuning, capo, program, channel, instrument, drum / tab /
    fretted), master bars, rhythms (dotted, triplets, rests, shared ids);
  - GP5's second voice, and empty bars;
  - strings and pitch, ties (fret kept) and dead notes;
  - per-note dynamics, and tempo changes at the bar start and mid-bar;
  - a GP5 song through `track_to_midi`.
  `test_mixins.py` covers the dynamics mixin and the builder, and
  `test_gp2midi_dynamics.py` covers a note dynamic overriding the beat's.

**Checked:**

- 489 tests pass and pyflakes is clean.
- GPIF output is unchanged: 126 `.mid` files and `gpinfo.py --json` are
  identical to the step 2 commit. `gpinfo` still lists only GPIF files
  (step 7).
- All 32 GP3–5 files in `in/` load (2.8 s) and convert with the defaults,
  with `--no-humanize` and with `--mpe`: 172 files each, no errors.
- Against PyGuitarPro's own data, across all 172 tab tracks:
  - Struck pitches (not ties) are identical on every track.
  - Note-on ticks match each beat's start exactly on 169 tracks. Three
    differ by up to 5.6 ticks, from rounding each quintuplet or septuplet beat to whole ticks.
    That is the same per-beat rounding as GPIF, and the error resets at
    every bar.
- `pip install .` without the extra loads GPIF files, and a GP4 file
  gives "needs PyGuitarPro: pip install pyguitarpro". With `.[gp5]`, the
  GP4 file loads.

**Not yet:** articulations (steps 4–5) and grace notes. The capo is
stored but not added to the pitch, as for GPIF. Whether GP3–5 frets are
relative to the capo is still to be checked against a Guitar Pro export
(step 6); 8 tracks in the local files have one.

### Step 4: simple articulations (done)

**Done:**

- `PyGuitarProMixin.convert_note` now also gets the beat, and maps:
  - `accentuatedNote` → accent `'normal'`, and `heavyAccentuatedNote` →
    `'heavy'`, which wins;
  - `ghostNote`, `staccato` and `palmMute` to the model fields of the same
    meaning (dead notes were done in step 3);
  - note `vibrato` → `'slight'`. The beat's `effect.vibrato` is GP's
    "wide vibrato" flag (GP3/4 beat flag 0x02, read by PyGuitarPro), so it
    makes every note of the beat `'wide'`, overriding the note's own.
  - slides, through `SLIDES_IN` / `SLIDES_OUT`: `intoFromBelow` /
    `intoFromAbove` → `slide_in`, and shift / legato / out down / out up →
    `slide_out`. The out slides are checked in GPIF's flag order, first
    wins. A GP5 note can have one of each.
- What each version can store, found with round trips through
  PyGuitarPro and noted in `test_gp345.py`:
  - GP3: ghost, vibrato and beat vibrato, and slides. Every slide reads
    back as a shift slide, since GP3 has a single slide flag. There's no
    accent, staccato or palm mute.
  - GP4: adds accent (not heavy), staccato, palm mute and all six slide
    types, one per note.
  - GP5: everything above, including heavy accents and a slide in plus a
    slide out on one note.
- Tests in `test_gp345.py`:
  - each note flag in each version that stores it, and absent otherwise
    (5 version / flag pairs are skipped as unstorable);
  - beat vibrato → wide;
  - each slide type in GP4 and GP5;
  - GP3's slide;
  - GP5 in + out;
  - a GP5 song through `track_to_midi`: palm mute at half length and 8
    softer, accent 16 louder, staccato at half length.

**Checked:**

- 520 tests pass (5 skipped), and pyflakes is clean.
- GPIF output is unchanged: 126 `.mid` files and `gpinfo --json`.
- All 32 GP3–5 files convert with the defaults and with `--mpe`. Against
  step 3, 111 of the 172 MIDI files changed, and 87 now have pitch bends
  (from slides and vibrato) where none had any. Note-ons and note-offs
  balance per channel and pitch in every file.
- In all 32 files, every flag count in the converted scores equals the
  count in PyGuitarPro's data, from the notes of the voices kept:
  - accent 1,053 normal and 46 heavy
  - ghost 1,978, staccato 2,603, palm mute 4,911, dead 3,216
  - vibrato 1,324 slight and 30 wide
  - slides in 68 below and 9 above
  - slides out 1,263 legato, 440 shift, 322 down and 26 up

### Step 5: hammer-ons, bends, harmonics, grace notes, strokes (done)

**Done** (`readers/gp345.py`):

- **Hammer-on / pull-off.** GP3–5 flag the note the slur starts from,
  which becomes `hopo_origin`. The destination is the note on the same
  string in the next beat of the same voice, across bar lines, but not a
  tie; a rest in between breaks the slur. `convert_beat` keeps the
  pending strings per voice in a set, carried between measures by
  `convert_song`'s `hammers` dict (per track, per voice).
  The real files confirm the flag marks the origin. Of 2,798 flagged
  notes, only 7 have no note on their string in the next beat, but 924
  have none in the previous beat. 2,862 of the 2,869 origins (including
  grace hammers) found a destination.
- **Bends:** points → `bend_curve(points, position_scale=12,
  semitone_scale=2)`, since values are quarter tones.
- **Harmonics** (`convert_harmonic`):
  - Natural: the node is the note's fret.
  - Tapped: the tapped fret (absolute: GP5 stores it, and PyGuitarPro
    sets fret + 12 for GP4) minus the note's fret. 12 if there's no fret.
  - Artificial: the interval of the harmonic's pitch class and octave
    above the fretted pitch, `(pitch − fretted) mod 12 + 12 × octaves`
    with loco 0, 8va 1, 15ma 2, mapped to a node by
    `ARTIFICIAL_HARMONIC_NODES` (+12 → 12, +19 → 7, +24 → 5, +28 → 4,
    +31 → 3.2). Other intervals, the "bassa" octaves and GP3's
    pitch-less artificial harmonics give no harmonic, so the note plays
    at its fretted pitch.
  - Pinch and semi: no node in the format, so it's an assumption: pinch
    7 (+19, octave + fifth), semi 12 (+12). This affects 1 pinch and 18
    semi harmonics in the local files.
  - For GP4, PyGuitarPro reads code 15 as +19 and 17 as +24, opposite to
    its own docstring ("n + 5" / "n + 7"). That affects the 8 artificial
    harmonics in the local GP4 files, and is to check against Guitar Pro
    (step 6).
- **Grace notes** (`convert_grace`):
  - A main note's `GraceEffect` becomes a grace beat inserted before the
    main beat, holding one grace note per main note that has one, on the
    main note's string.
  - The beat is `'on'` if any grace is on the beat, else `'before'`. Its
    rhythm is the longest grace duration (16th / 32nd / 64th / 128th);
    gp2midi uses it only with `--grace-length 0`.
  - The grace note has the grace fret, the dead flag (fret −1 in GP3/4)
    and a dynamic from its velocity.
  - Transitions: hammer → the grace is the hammer-on origin and the main
    note the destination; slide → a legato slide into the main note;
    bend → a bend up to the main note's fret (the main note still sounds
    as written).
- **Strokes:** `stroke.direction` → `brush`; `pickStroke` →
  `pick_stroke`. Rasgueado and stroke speed are ignored.
- What each version stores, found by round trips:
  - GP3: no tapped, pinch or semi harmonics, no artificial-harmonic
    pitch, no on-beat graces and no pick strokes.
  - GP4: no on-beat graces.
  - Bends, hammer flags and brush strokes are in all three.
- Tests in `test_gp345.py`:
  - hammer-on pairs, also across a bar line, and broken by a rest or a
    tie;
  - bends;
  - natural, tapped, pinch and semi harmonics;
  - GP5 artificial harmonics, including intervals with no node and a
    bassa octave, and GP3's pitch-less one;
  - every node in `ARTIFICIAL_HARMONIC_NODES` checked against
    `harmonic_interval`;
  - grace beats: position, rhythm, fret, dynamic, on-beat, all four
    transitions, and dead graces per version;
  - brush and pick strokes;
  - a GP5 song through `track_to_midi`: the bend's pitch wheel, a grace
    sounding before its beat, and a softer hammer-on destination.

**Checked:**

- 571 tests pass (5 skipped), and pyflakes is clean.
- GPIF output is unchanged: 126 `.mid` files and `gpinfo --json`.
- All 32 GP3–5 files convert with the defaults, `--mpe` and
  `--no-humanize`, 172 files each.
- In the `--no-humanize` output, compared with PyGuitarPro's data, every
  struck main note is there at its beat's start (within 6 ticks of tuplet
  rounding). Harmonics are left out of this check because they change
  pitch, and so are the main notes delayed by an on-beat grace. 592 notes
  are extra: 412 grace notes, the harmonics, and the extra layer of semi
  harmonics. Note-ons and note-offs balance in every file.
- Across the files: 2,869 hammer-on origins and 2,862 destinations,
  1,211 bends, 419 grace beats (400 before, 19 on), 85 brush strokes and
  60 pick strokes.
- Harmonics: 149 of the 161 in the files (102 natural, 26 artificial, 18
  semi, 2 tapped, 1 pinch). The other 12 have no node and play at their
  fretted pitch: 4 GP5 tapped harmonics that tap their own fret (12 on
  fret 12), 1 natural harmonic on an open string, and 7 artificial
  harmonics whose interval isn't a harmonic (or whose octave is "loco"
  on the note's own pitch class).

### Step 6: cross-format check (done)

**Files:** the user exported two GPIF songs from `in/` from Guitar Pro 8
as GP5 (v5.00), into `tmp/gp8To5/`, with the same file names. They were compared with
`in/<name>.gp` at the score level (note by note, keyed by track, bar,
tick in the bar and string) and the MIDI level (`gp2midi
--no-humanize`). The comparison scripts are in the session scratchpad,
not the repo.

**Found and fixed: GPIF dots and tuplets were ignored.** Every GP6–8 file
in `in/` writes them as attributes: `<AugmentationDot count="1"/>` (73
rhythm definitions) and `<PrimaryTuplet num="3" den="2"/>` (43), plus 2
nested `<SecondaryTuplet num="5" den="4"/>`. `parse_rhythms` only read
`<AugmentationDot><Enable>true</Enable>` and `<PrimaryTuplet><Num>`
/ `<Den>`, forms no file in `in/` uses, so dotted notes and tuplets have
been timed as plain notes since the start of the project.

- Before the fix, of 18,031 GPIF voices, 3,455 were shorter than their
  bar (missing dots) and 515 longer (missing tuplets). After it, all
  18,031 add up exactly to their bar.
- The GP5 exports exposed it: PyGuitarPro times them correctly, so the
  same bar of a rhythm guitar part was 2,040 ticks from the `.gp` file
  but 1,920 from the `.gp5`.
- Fix: `parse_rhythms` reads the attributes, with the child forms as
  fallbacks, and multiplies a secondary tuplet into the primary one.
  `RhythmMixin.rhythm` takes a dot count (`dots`, so two dots → × 1.75)
  instead of `dotted`, and True still counts as one.
- New tests: `test_parse_rhythms_gp8_forms` and
  `test_parse_rhythms_secondary_tuplet` (`test_parsers.py`).
- **GPIF output changes:** 88 of the 107 default MIDI files from `in/`.
  `gpinfo --json` is unchanged.

**Results after the fix:**

- **Tracks:** same names, tunings, capos (all 0), channels and drum / tab
  flags. The export changed some MIDI programs: in one file the guitars
  29 → 26 and 30, the bass 34 → 36, and a "Keyboards, guitar fills"
  track violin (48) → Overdriven Guitar (29). The last one is therefore
  fretted in the GP5 file, since classification goes by program there.
- **Notes:** every note of every guitar, bass and vocal track matches in
  position, string and fret, and in every articulation field except:
  - bends: the export repeats each point and adds an end point, but the
    curves have the same shape;
  - 4 bass "slide out down" (GPIF flag 4) exported as shift slides;
  - 2 "slide in from below" dropped by the export.
  PyGuitarPro decodes GP5 slides bit for bit, so those 6 are in the
  exported file.
- **Drums:** a few flams in one bar differ. Drums aren't
  converted by default.
- **MIDI** (`--no-humanize`, all 9 tab tracks): all 14,574 notes are
  identical in tick, pitch, velocity and length. With `--vibrato-depth
  0`, pitch bends are identical except where those 6 slides differ.
- **Vibrato** bends differ because the tempos differ. The export rounds
  tempos to whole BPM (148.999 → 148) and moves mid-bar tempo changes to
  the bar start. In one `.gp` file, a change at bar 5 position 0.125 stops gp2midi's tempo loop (decision 3), so that MIDI
  stays at 76 BPM for the rest of the song. From the GP5 export, the
  later changes apply (20 BPM at bar 22, 110 at bar 90, 210 at bar 138,
  ...). Vibrato rate is in Hz, so its curve follows the tempo.

**Not settled by the exports:** these two songs have no capo and no
harmonics, and no GPIF file in `in/` has a capo. Settling GP4's
artificial-harmonic codes and the pinch / semi nodes needs the opposite
direction: GP3–5 files from `in/` opened in Guitar Pro 8 and saved as
`.gp`, so GP8's reading of them is the reference. The user couldn't make
those exports, so the step was finished without them (2026-10-20). The
capo was settled from the files themselves (below), and the harmonic
mappings stay unverified assumptions. Files that would settle them, if
the exports become possible: GP3–5 files with a capo (one GP4 file has
capo 2 on 5 tracks), with GP4 artificial harmonics (3 files, 8
harmonics), with pinch, semi and GP5 artificial harmonics, and with GP5
tapped harmonics on their own fret.

**Capo, settled from the files themselves.** The test was whether a
capo track's pitch classes (weighted by note length) match those of the
song's tracks without a capo (bass, vocals, strings) better as written
or with the capo added (Pearson correlation of the 12-bin profiles):

| File | Capo tracks | As written | Capo added |
|---|---|---|---|
| File A (GP4) | 5, capo 2 | +0.06 to +0.48 | +0.70 to +0.82 |
| File B (GP5) | 1, capo 2 | +0.49 | +0.75 |
| File C (GP5) | 2, capo 12 | +0.92 / +0.69 | the same: an octave doesn't show |

So GP3–5 frets count from the capo, and the readers were playing capo
tracks a capo's worth too low. Fix:

- `convert_beat` sets each note's `Note.midi` (and each grace note's) to
  the sounding pitch: string tuning + capo + fret (`_pitch`). gp2midi
  already prefers `note.midi` over tuning + fret.
- `theory.harmonic_pitch` now bases natural harmonics on `fretted −
  note.fret`, the open string with any capo, instead of
  `tuning[string]`. For every file without a capo that's the same number,
  so GPIF output is byte-identical (126 files). For a GP8 file the `Midi`
  property is the fretted pitch even for harmonics (see CLAUDE.md
  Harmonics).
- GPIF capo semantics stay unknown: no GPIF file in `in/` has a capo.
  GP8's `Midi` property presumably includes it; a GP6 file falls back to
  tuning + fret, with no capo.
- In the GP3–5 output, exactly the 8 capo tracks change. File C's
  capo-12 tracks now span MIDI 60–81 and 66–81, and file B's guitar
  42–74.
- Tests: `test_capo_raises_the_pitch` (GP3/4/5, main and grace notes)
  and `test_capo_natural_harmonic_through_gp2midi`.
  `test_strings_and_pitch` now expects `Note.midi` to be set.

**Checked at the end of the step:** 577 tests pass (5 skipped), and
pyflakes is clean.

### Step 7: docs, packaging, gpinfo, merge (done)

**Done:**

- `gpinfo.py`: `GP_SUFFIXES` includes `.gp3`, `.gp4` and `.gp5`, so a
  directory listing (default `in/`) covers every format. `file_info`
  needed no change. GP3–5 tracks show their General MIDI instrument name,
  and `tuning_label` finds basses by "Bass" in it.
- `gp2midi.py`: the module docstring, `--help` description and `input`
  help name the GP3–5 formats.
- README: the duplicated "See `docs/formats.md`" removed; the library
  section says GP3–5 files need PyGuitarPro (`pip install -e
  '/path/to/gp-2-midi[gp5]'`) and that `load_score` picks a reader per
  format.
- CLAUDE.md: a GP5 example command, the `[gp5]` install, gpinfo's
  formats, and the test list.
- Packaging was done in step 3 (the `gp5` extra, the pin in
  `requirements.txt`, the description).
- Test: `test_gp5_file_info_and_directory_listing` (`test_gpinfo.py`):
  a GP5 song built in code is listed by `find_files` (a `.txt` beside it
  isn't). It checks title and artist, that only fretted tracks are shown
  (not the vocal), drop D with capo 3, the instrument name, and the
  bass's standard tuning.

**Checked:**

- 578 tests pass (5 skipped), and pyflakes is clean.
- GPIF MIDI (126 files, `--all-tracks`) is identical to the step 6
  commit.
- `gpinfo --json` over `in/` now lists 51 files instead of 19. The 19
  GPIF entries are identical; the other 32 are the GP3–5 files.
- All 51 files in `in/` converted with default settings into
  `out/gp345/` (279 MIDI files, no errors) for the user to check. The
  branch was merged after that check.
