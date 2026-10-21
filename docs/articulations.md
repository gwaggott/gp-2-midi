# Guitar articulations: status and plan

Analysis from 2026-10-07. **Status:** the planned list is done: ties, bends,
dynamics, accents, ghost notes, staccato, hammer-ons/pull-offs, palm muting,
dead notes, vibrato and slides, plus grace notes, harmonics and optional
per-string MIDI channels (see the implementation notes at the end). Brush,
arpeggio and pick-stroke markings are used by humanize's strum spread
(`docs/humanize.md`). Still unhandled: whammy bar and the minor items listed
under the table.

## What the input files use

Survey of the 22 files in `in/` at the time (17 `.gp`, 5 `.gpx`). "Files" is
how many contain the element at least once.

| Articulation | GPIF data | Files | Current behaviour |
|---|---|---|---|
| Hammer-on / pull-off | Note props `HopoOrigin` / `HopoDestination` | 21 | **Done:** softer destination; optional legato overlap |
| Slides | Note prop `Slide` (bit flags for slide type) | 19 | **Done:** pitch-bend glides |
| Vibrato | `<Vibrato>` element on Note (Slight/Wide) | 18 | **Done:** pitch-bend wave |
| Bends | Note props `Bended`, `Bend{Origin,Middle,Destination}{Value,Offset}` (`BendMiddleOffset1/2`) | 18 | **Done:** pitch-bend curve |
| Dead notes | Note prop `Muted` | 16 | **Done:** short click, softer |
| Grace notes | `<GraceNotes>` on Beat | 14 | **Done:** before / on the beat, no bar time |
| Palm muting | Note prop `PalmMuted` | 8 | **Done:** shorter, slightly softer; whole onset muted if any note is |
| Harmonics | Note props `Harmonic`, `HarmonicType`, `HarmonicFret` | 5 | **Done:** harmonic pitch |
| Whammy bar | `<Whammy>`, Beat props `WhammyBar*` | 5 | Ignored |
| Accents and dynamics | `<Accent>` on Note (bit flags), `<Dynamic>` on Beat | all | **Done:** velocity; staccato halves length |
| Ghost notes | `<AntiAccent>Normal</AntiAccent>` on Note | – | **Done:** softer velocity |
| Brush (strum) | Beat prop `Brush` (`<Direction>Down/Up</Direction>`) | 10 | **Done** (humanize): sets the stroke direction, 15 ms per string |
| Arpeggio | `<Arpeggio>Down/Up</Arpeggio>` on Beat | 4 | **Done** (humanize): sets the stroke direction, 40 ms per string |
| Pick stroke | Beat prop `PickStroke` (`<Direction>`, assumed) | 0 | **Done** (humanize): sets the stroke direction, 6 ms per string |

The Brush, Arpeggio and Pick stroke file counts are from the humanize survey
of the 19 files in `in/` on 2026-10-14 (see `docs/humanize.md`).

Also present but unhandled: `LetRing` (13), `Fadding` volume swells (4),
`Slapped` (1), `Wah` (1). They aren't parsed, but
are readable from the raw XML the model keeps: `note.element.find('LetRing')`,
`beat.properties['Brush']`, `beat.element.find('Whammy').attrib`, ...

## How each could be approximated in MIDI

- **Bends, vibrato, slides, whammy:** pitch-bend messages. Pitch bend affects
  the whole channel, so a bend also shifts any other note sounding at the same
  time (`--channel-per-string` gives each string its own channel). Set the bend range to at least
  ±2 semitones, ideally ±12 via an RPN 0 message. GP bend values are in 1/100
  of a whole tone (100 = full bend = 2 semitones); offsets are measured over
  the note's length (0–100).
  Vibrato is a pitch-bend wave, or CC1 (modulation) for a simpler version.
- **Hammer-ons and pull-offs:** lower velocity on the destination note, and
  optionally overlap the previous note slightly so sound modules that support
  legato play it smoothly.
- **Palm muting and dead notes:** shorter notes (about 30–50% length for palm
  muting, very short for dead notes) and lower velocity. Some guitar sound
  modules offer dedicated muted sounds via a different program or keyswitch,
  but that's specific to the module.
- **Accents and dynamics:** map `Dynamic` (PPP…FFF) to velocity, with a boost
  for accents.
- **Harmonics:** work out the pitch from `HarmonicFret`, e.g. 12 → +12
  semitones, 7 → +19, 5 → +24.
- **Grace notes:** play them just before the main note and keep them out of
  the beat's length.

## Suggested order

1. ~~Bends~~ (done).
2. ~~Dynamics and accents, hammer-on/pull-off velocity~~ (done).
3. ~~Palm muting and dead-note lengths~~ (done).
4. ~~Vibrato and slides~~ (done).

One MIDI channel per string is done (`--channel-per-string`, or as MPE with
`--mpe`). Possible next
step: whammy bar (beat-level, also pitch bend; with per-string channels it
would bend every string's channel).

Parsing goes in `src/gpif/readers/gpif_xml.py` (`GpifContentMixin.parse_notes` /
`parse_beats`; for GP3–5 files, their reader too, see `docs/formats.md`); MIDI output
goes in `track_to_midi` in `src/gp2midi.py`.

## Bends: implementation notes

- **Parsing** (`gpif.bend_points`): builds `[(fraction, semitones), ...]` from
  origin, middle and destination points. Defaults when GP6 omits them: origin
  offset 0, destination offset 100, middle at 50. GP8 writes middle points even
  for a plain bend, sometimes after the destination (e.g. destination at 26%,
  middle at 50%); middle points outside origin..destination are dropped.
  `Bended` with no values is treated as no bend.
- **Data seen:** 140 distinct curve shapes; values from 12.5 (¼ semitone) to
  250 (5 semitones). Hence the default range of ±12 semitones.
- **MIDI** (`gp2midi.bend_events`): pitchwheel messages every
  `BEND_STEP_TICKS` (20) plus each breakpoint, kept before the note's end
  tick. A new unbent note resets the wheel to 0; a tied continuation without
  its own bend holds the previous value. Repeated values are dropped, so
  tracks with no bends are byte-identical to before. RPN 0 sets the range
  (`--bend-range`, default 12) only on tracks that bend.
- **Known limitation:** pitch bend is channel-wide. 129 beats in the inputs
  have a bent note alongside other notes (e.g. a bend against a held string);
  every note sounding on the channel bends with it. `--channel-per-string`
  fixes this (see its notes below).

## Dynamics and accents: implementation notes

- **Data seen** (19 files): every beat has a `<Dynamic>`; 72% are F, the rest
  spread from PPP to FFF. `<Accent>` is a bit field: 0x01 staccato (884
  notes), 0x04 heavy accent / marcato (2), 0x08 accent (33); 9 = staccato +
  accent (1). `<AntiAccent>Normal</AntiAccent>` marks a ghost note (81).
- **Parsing:** `parse_beats` gives `dynamic` (upper-case string or None);
  `parse_notes` gives `accent` (None / 'normal' / 'heavy'; heavy wins if both
  bits are set), `staccato` and `ghost`.
- **MIDI** (`gp2midi.note_velocity`): PPP 16, PP 32, P 48, MP 64, MF 80, F 96,
  FF 112, FFF 127 (missing or unknown → MF). Accent +16, heavy accent +32,
  ghost −32, clamped to 1–127. Staccato notes sound for half their written
  length (a tie continuation still extends them to the tied end).
- `--velocity N` now means "fixed velocity N for every note, ignoring
  dynamics, accents and ghost notes"; without it, velocity comes from the
  score. Staccato length applies either way.
- Because most music is marked F, typical output is now velocity 96 where it
  was 80 before.

## Hammer-ons and pull-offs: implementation notes

- **Data seen:** `HopoOrigin` / `HopoDestination` properties, each just
  `<Enable/>`, in 18 of 19 files: 589 destination note elements, played 2114
  times (GPIF reuses note elements across repeated beats). 69 notes are both
  (chains like 5h7p5). Hammer-on vs pull-off isn't stored; it follows from
  the pitch direction, and both are treated the same.
- **Parsing:** `parse_notes` gives `hopo_origin` and `hopo_dest`.
- **Velocity:** destination notes are softer by `--hopo-cut N` (default 16,
  one dynamic level; 0 disables), applied after dynamics/accents/ghost in
  `note_velocity`. `--velocity N` overrides it like everything else.
- **Legato overlap** (`--hopo-overlap TICKS`, default 0 = off): the previous
  note on the same string is held into the destination by that many ticks
  (capped at the destination's length), so mono/legato synth patches slur
  instead of retriggering. Only applied when that previous note is flagged
  `hopo_origin`, has a different pitch, and ended exactly where the
  destination starts (not cut short by staccato or a rest); a tied origin
  works. Off by default because on a polyphonic patch both notes sound
  together for the overlap. 2099 of the 2114 destinations qualify.

## Palm muting and dead notes: implementation notes

- **Data seen:** note properties `PalmMuted` and `Muted` (dead note, x in
  tab), each just `<Enable/>`. Palm muting: 582 note elements, played 4302
  times (most in heavy rock rhythm parts). Dead notes: 957 elements,
  played 6248 times (most in rhythmic, funky parts). No note
  is both; 24 palm-muted notes are hammer-on/pull-off destinations and 6 are
  tie continuations.
- **Parsing:** `parse_notes` gives `palm_muted` and `dead`.
- **Whole onsets** (`--palm-mute-chords`, on by default;
  `gp2midi.palm_mute_chords`): the picking hand mutes every string it
  strikes, so when one note struck at an onset (tick and staff, any voice)
  is palm muted, the others struck there are treated as palm muted too,
  between the passes (a `palm_muted` copy of the note in the occurrence).
  Tied continuations neither count nor change, and dead notes stay dead
  notes. Tabs often mark only part of a chord: in one sample file, two
  rhythm guitar tracks mark the A-string note of nearly every muted E5
  power chord but not the low E (1,081 onsets). Across the sample files,
  7 tracks change: those two (544 and 537 notes) and 42 notes in five
  others (in one, some are a muted note in one voice struck with an open
  one in another). `--no-palm-mute-chords` keeps the marks per note, and its
  output is byte-identical to before.
- **Length** (`gp2midi.sounding_ticks`): palm-muted notes sound for
  `--palm-mute-length` (default 0.5) of their written length; dead notes for
  at most `--dead-note-length` ticks (default 30, a 64th note). With staccato
  too, the shortest wins. A tie continuation still extends the note to the
  tied end. A shortened note doesn't get the hammer-on/pull-off legato
  overlap, since it no longer ends where the next note starts.
- **Velocity:** `--palm-mute-cut` (default 8) and `--dead-note-cut` (default
  16) in `note_velocity`, stacking with the other adjustments;
  `--velocity N` overrides them.
- Dead notes keep their fretted pitch. A synth with a muted-guitar sound or a
  keyswitch would do better, but that's specific to the sound module.
- Side effect: when a track's last note is shortened, its `end_of_track`
  marker moves earlier (it's placed at the last event).

## Vibrato and slides: implementation notes

- **Data seen:** `<Vibrato>` on 334 note elements (331 Slight, 3 Wide); 9
  beats have whammy-bar vibrato (`VibratoWTremBar`), not handled. `<Slide>
  <Flags>` on 434 note elements: 1 shift slide to next note (183), 2 legato
  slide to next (132), 4 slide out down (70), 8 out up (3), 16 slide in from
  below (43), 32 in from above (1); combinations seen are 18 (in-below +
  legato) and 20 (in-below + out-down). Flags 0x40 / 0x80 (pick scrape) are
  not in the inputs. 17 notes have both a bend and vibrato.
- **Parsing:** `parse_notes` gives `vibrato` ('slight' / 'wide' / None),
  `slide_in` ('below' / 'above' / None) and `slide_out` ('shift' / 'legato' /
  'down' / 'up' / None; first matching flag wins).
- **Two passes:** `track_to_midi` first walks the score into a list of note
  occurrences (tick, duration, note, pitch, dynamic, bpm, plus tempo
  changes), then emits MIDI from that list. Slides into the next note need
  lookahead: the target is the occurrence on the same string that starts
  exactly when the slide note ends (possibly in the next bar), and it must
  have a different pitch. With vibrato and slides off, output is
  byte-identical to the single-pass version.
- **Pitch curves** (`gp2midi.note_pitch_curve`): bend, vibrato and slides are
  separate parts added together, sampled by `curve_events` (which
  `bend_events` now wraps).
  - Vibrato: `depth × (1 − cos)/2`, so it only goes sharp, like finger
    vibrato. Peak `--vibrato-depth` semitones for slight (default 0.5), double
    for wide; `--vibrato-rate` Hz (default 5.5), converted to ticks with the
    bar's tempo. Sampled at least 12 times per cycle.
  - Slide in: starts `--slide-distance` semitones (default 5) below / above
    and glides onto the note over `--slide-time` ticks (default 120, capped at
    the note length).
  - Slide out down / up: glides `--slide-distance` away over the last
    `--slide-time` ticks.
  - Shift / legato slide: glides to the next note's pitch over the last
    `--slide-time` ticks; the next note then starts at its own pitch with the
    wheel reset. Shift: the next note is picked normally. Legato: it's
    softer by `--hopo-cut`, like a hammer-on (not cut twice if it is also a
    hammer-on destination). If there's no target note, there's no glide.
- `--vibrato-depth 0` and `--slide-time 0` turn the features off (including
  the legato velocity cut).
- **Channel-wide pitch bend:** chord slides (e.g. power chords) work well
  because every note moves by the same interval, but vibrato on one note of a
  chord wobbles the whole chord (unless `--channel-per-string` is on).
- Output size: pitchwheel messages across all tracks went from about 14,500
  to 77,300, mostly vibrato.

## Grace notes: implementation notes

- **Data seen:** a grace note is its own beat, just before the main beat,
  with `<GraceNotes>BeforeBeat</GraceNotes>` (271 of 274 played) or `OnBeat`
  (3). 99 grace beats, played 274 times, never more than one in a row.
  Written length is almost always a 32nd (60 ticks), sometimes a 64th or
  128th. 239 are on the same string as the main note: 84 hammer-on/pull-off
  graces, 55 slide graces. 9 drum tracks have them (flams).
- **Bug fixed:** grace beats used to take their written length in the bar,
  so the main note and the rest of the bar played a 32nd late and spilled
  into the next bar (151 bar/voice combinations).
- **Parsing:** `parse_beats` gives `grace` ('before' / 'on' / None).
- **Timing** (first pass of `track_to_midi`): grace beats don't advance the
  bar cursor. Before-beat: the grace note sounds from main − length to main.
  On-beat (or a before-beat grace at tick 0, which can't start earlier): it
  sounds on the beat and the main note starts that much later and is that
  much shorter. Length is the written length, or `--grace-length TICKS`.
- **Same string:** between the passes, the previous note on a grace note's
  string is shortened to end where the grace note starts, so its pitch curve,
  tie extension and slide target all fit the new length. Not on drum tracks
  (or any track without a tuning), where every note reads as string 0.
- **Velocity:** grace notes are softer by `--grace-cut` (default 16), on top
  of the usual adjustments.
- **Interactions** need no special code because the grace note ends exactly
  where the main note starts: hammer-on graces get the hopo velocity and
  `--hopo-overlap`; slide graces glide into the main note over the whole
  grace length (slide time is capped at note length).
- **Verification:** the 92 tracks without grace notes are byte-identical to
  before; in the 34 with them, every note is still present and only timing
  and velocity change.

## Harmonics: implementation notes

- **Data seen:** `HarmonicType` (`<HType>`) and `HarmonicFret` (`<HFret>`,
  sometimes `12.000000`), plus `Harmonic` `<Enable/>` in GP8 only. In the
  inputs: artificial at 12 (21 elements, 119 played) and 7 (2, 63), natural
  at 12 (6, 6), pinch at 2.4 (1, 1), across 6 tracks, mostly in one file.
  7 harmonic note elements are tie continuations (22 plays).
- **GP8 `Midi` is the fretted pitch** even for harmonics (e.g. string 4 fret
  12 artificial: `Midi` 71 = 59 + 12), so the harmonic pitch is calculated.
- **Parsing:** `parse_notes` gives `harmonic` = `Harmonic(type, fret)` or None
  (types: natural, artificial, pinch, tap, semi, feedback).
- **Interval** (`gpif.harmonic_interval`): fret f is a fraction
  d = 1 − 2^(−f/12) of the string; a node is where d ≈ k/n (within 0.012 of
  the string length, n ≤ 12), sounding the n-th partial, 12·log2(n)
  semitones up, rounded: 12 → +12, 7 / 19 → +19, 5 / 24 → +24,
  4 / 9 / 16 → +28, 3.2 → +31, 2.7 → +34, 2.4 → +36. Rounding ignores the
  natural tuning of partials (the 5th is 14 cents flat) to avoid channel-wide
  pitch bend. No node (e.g. 12.5, or 1 with n capped at 12) → 0.
- **Pitch** (`gpif.harmonic_pitch`): natural harmonics count from the open
  string (tuning, or fretted − fret if there's no tuning); the other types
  from the fretted pitch. No node, or a result outside 0–127, → the note
  plays at its fretted pitch.
- **Semi harmonics** play both the fretted note and the harmonic, the
  harmonic softer by `SEMI_HARMONIC_CUT` (16) on top of `--harmonic-cut`.
  None in the inputs.
- **Switches:** `--harmonic-cut N` (default 0, so harmonics are as loud as GP
  plays them) and `--no-harmonics` (fretted pitch, for synths with their own
  harmonics sound).
- **Ties:** continuations carry the same harmonic, so they get the same pitch
  and extend the note as usual; for semi harmonics each layer extends.
- **Verification:** with `--no-harmonics` all 126 tracks are byte-identical
  to before. By default only harmonic notes change pitch (161 notes in 5
  tracks: +12, +19, +36); timing is unchanged everywhere. The natural
  harmonics in the samples are at the 12th fret, so their pitch doesn't
  change.

## Per-string channels: implementation notes

- **Switch:** `--channel-per-string` (off by default; output is then
  byte-identical to before). Each string gets its own MIDI channel, so a
  bend, vibrato or slide only moves the notes on its string, as on a real
  guitar. This is the layout of a guitar controller's mono mode (Roland GK,
  Fishman TriplePlay) and of multitimbral synths with the same patch loaded
  on each channel.
- **Channels** (`gp2midi.string_channels`): string 1 (the highest, GPIF's
  last string) on channel 1 (index 0), string 2 on channel 2, and so on,
  skipping channel 10 (index 9, GM drums). That leaves 15 channels; tracks
  with more strings, drum tracks and tracks without a tuning keep one
  channel. The track's own channel is ignored. Each output file is a single
  track, so files from different tracks reuse the same channels.
- **Header:** the program change goes to every string channel; RPN 0 (bend
  range) only to channels that bend.
- **Per channel:** a plain note resets the wheel on its own channel only;
  the repeat filter, final reset and tie extension (keyed by channel and
  pitch) all work per channel, so the same pitch on two strings ties
  separately. `--hopo-overlap` now overlaps two notes on the same channel,
  which is what a mono / legato patch needs.
- **Verification:** across all 126 tracks every note has the same tick,
  pitch, velocity and length as with one channel; note-ons and offs balance
  per channel and every channel ends unbent. 54 tracks bend on more than one
  channel.

## MPE: implementation notes

- **Switch:** `--mpe` (off by default; the default and
  `--channel-per-string` output stay byte-identical). The per-string
  channels laid out as an MPE (MIDI Polyphonic Expression) lower zone, for
  MPE synths. It implies one channel per string, and wins over
  `--channel-per-string` if both are given.
- **Channels** (`MPE_MANAGER_CHANNEL`, `MPE_MEMBER_CHANNELS`): channel 1
  (index 0) is the manager channel; string 1 (the highest) goes on
  channel 2, string 2 on channel 3, and so on. Channel 10 is used like any
  other (MPE has no drum channel), so up to 15 strings fit. The same tracks
  as with `--channel-per-string` keep one channel (drums, no tuning,
  multi-staff, more than 15 strings) and are written as plain MIDI, with
  no MPE header.
- **Header:** the MPE Configuration Message (`gp2midi.mpe_configuration`:
  RPN 6 on the manager channel, value = the number of strings, then RPN
  null), then the program change on the manager channel only (zone-wide),
  then RPN 0 (`--bend-range`) on every member channel, bending or not:
  the configuration message resets the member bend range to MPE's default
  of 48 semitones, and some synths only take it from the member channels.
- **Notes and bends** are the same as with `--channel-per-string`, one
  channel up: each note's wheel is set (or reset to 0) just before its
  note-on, as MPE asks.
- **Timbre (CC74) = palm muting:** each struck note's channel gets CC74
  just before its note-on (at the strummed tick, sort key `SK_RESET`):
  `--palm-mute-timbre` (default 127) for a palm-muted note,
  `--open-timbre` (default 0) otherwise. Tied continuations send nothing,
  and `drop_redundant_timbre` drops values that repeat the channel's
  current one (the first on each channel is always sent). Only with
  `--mpe`; velocity and length still change for palm muting as before.
  It follows `--palm-mute-chords`, so a chord is muted or open as a whole
  unless that's turned off.
  GPIF marks palm muting per note, on or off (`PalmMuted`), with no
  strength. Tracks have a `<PalmMute>` value (0 on most, 0.3–0.42 in four
  of the sample files), apparently a playback setting: heavily palm-muted
  rhythm guitars in another file have 0, so it isn't used.
- **Not sent:** channel pressure, MPE's other per-note control; a tab has
  nothing that maps cleanly to it.
- **Verification:** on three sample files (14 tracks), every note-on,
  note-off and pitch-wheel event matches the
  `--channel-per-string` output with the channel shifted up by one. With
  timbre added, all 107 sample MIDI files match the earlier `--mpe` output
  apart from CC74, and every note-on has a timbre set on its channel
  (one palm-muted rhythm guitar, per note: 548 of 1413 note-ons muted, 58
  CC74 messages; with `--palm-mute-chords`: 1092 muted, 96 messages).

## Brush, arpeggio and pick stroke: implementation notes

Part of humanize (on by default; `--no-humanize` turns it off). Full plan,
rules and verification are in `docs/humanize.md`.

- **Parsing:** `Beat.pick_stroke`, `Beat.brush` and `Beat.arpeggio`, each
  `'down'` / `'up'` / None. `Down` is taken as a downstroke (low string
  first), unconfirmed by any reference but matching the data (most strums
  are down). No input file has a pick stroke, so its XML form is assumed
  to match `Brush`.
- **Direction:** a marked stroke sets the onset's direction. Unmarked
  onsets get one from their place in the beat (on the beat down, off the
  beat up, on an eighth or sixteenth grid).
- **Spread:** the chord's notes start one after another, from the lowest
  struck string on a downstroke (highest on an upstroke): `--strum-time`
  (6 ms per string) for a pick stroke, `--brush-time` (15) for a brush,
  `--arpeggio-time` (40) for an arpeggio. Note-offs stay as written.
