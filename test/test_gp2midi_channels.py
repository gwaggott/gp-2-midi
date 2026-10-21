"""Tests for --channel-per-string and --mpe in gp2midi.py."""

from dataclasses import replace

from conftest import TRACK, convert
from gp2midi import MidiOptions, bend_value, drop_redundant_timbre, mpe_configuration, string_channels
from mido import Message
from gpif import TICKS_PER_BEAT, Staff

BEAT = TICKS_PER_BEAT
BEND = [(0.0, 0.0), (1.0, 2.0)]     # full bend over the note


def by_channel(msgs, kind):
    """{channel: [(tick, msg), ...]} for messages of one type."""
    out: dict[int, list] = {}
    for t, m in msgs:
        if m.type == kind:
            out.setdefault(m.channel, []).append((t, m))
    return out

# ---------------------------------------------------------------------------
# string_channels
# ---------------------------------------------------------------------------

def test_off_by_default():
    assert string_channels(TRACK) is None


def test_highest_string_gets_first_channel():
    assert string_channels(TRACK, MidiOptions(channel_per_string=True)) == [5, 4, 3, 2, 1, 0]


def test_drum_channel_skipped():
    track = replace(TRACK, staves=[Staff(tuning=list(range(40, 50)))])
    assert string_channels(track, MidiOptions(channel_per_string=True)) == [10, 8, 7, 6, 5, 4, 3, 2, 1, 0]


def test_single_channel_tracks():
    on = MidiOptions(channel_per_string=True)
    assert string_channels(replace(TRACK, is_drum=True), on) is None
    assert string_channels(replace(TRACK, staves=[Staff()]), on) is None
    assert string_channels(replace(TRACK, staves=[Staff(tuning=list(range(40, 56)))]), on) is None   # 16 strings

# ---------------------------------------------------------------------------
# track_to_midi
# ---------------------------------------------------------------------------

def test_notes_on_their_string_channel(tmp_path):
    msgs = convert(tmp_path, [{'string': 0}, {'string': 2}, {'string': 5}], channel_per_string=True)
    ons = [(m.channel, m.note) for _, m in msgs if m.type == 'note_on']
    offs = [(m.channel, m.note) for _, m in msgs if m.type == 'note_off']
    assert ons == [(5, 47), (3, 57), (0, 71)]
    assert sorted(offs) == sorted(ons)


def test_program_on_every_string_channel(tmp_path):
    msgs = convert(tmp_path, [{}], channel_per_string=True)
    programs = [(m.channel, m.program) for _, m in msgs if m.type == 'program_change']
    assert programs == [(c, 29) for c in range(6)]


def test_bend_against_held_string_is_polyphonic(tmp_path):
    # Bend string 3 while string 4 rings: only string 3's channel bends
    msgs = convert(tmp_path, [{'string': 3, 'bend': BEND}, {'string': 4}], chords=[[0, 1]],
                   channel_per_string=True)
    pw = by_channel(msgs, 'pitchwheel')
    assert set(pw) == {2}
    assert max(m.pitch for _, m in pw[2]) == bend_value(2, 12)
    assert pw[2][-1][1].pitch == 0                       # left unbent at the end
    rpn = {m.channel for _, m in msgs if m.type == 'control_change'}
    assert rpn == {2}                                    # bend range only where it bends


def test_single_channel_bend_moves_the_chord(tmp_path):
    msgs = convert(tmp_path, [{'string': 3, 'bend': BEND}, {'string': 4}], chords=[[0, 1]])
    assert {m.channel for _, m in msgs if m.type in ('note_on', 'pitchwheel')} == {0}


def test_plain_note_does_not_reset_other_strings(tmp_path):
    # String 3 vibrato over two beats (tied); string 4 picks on beat 2
    held = {'string': 3, 'vibrato': 'slight'}
    msgs = convert(tmp_path, [held, {**held, 'is_tie_dest': True}, {'string': 4}],
                   chords=[[0], [1, 2]], channel_per_string=True)
    pw = by_channel(msgs, 'pitchwheel')
    assert set(pw) == {2}
    assert any(t > BEAT and m.pitch != 0 for t, m in pw[2])   # still wobbling on beat 2


def test_same_pitch_on_two_strings_ties_separately(tmp_path):
    # E4 on string 4 (fret 5) and string 5 (open); only string 5 is tied over
    msgs = convert(tmp_path, [{'string': 4, 'fret': 5}, {'string': 5, 'fret': 0},
                              {'string': 5, 'fret': 0, 'is_tie_dest': True}],
                   chords=[[0, 1], [2]], channel_per_string=True)
    offs = {m.channel: t for t, m in msgs if m.type == 'note_off'}
    assert offs == {1: BEAT, 0: 2 * BEAT}

# ---------------------------------------------------------------------------
# --mpe
# ---------------------------------------------------------------------------

MPE = MidiOptions(mpe=True)


def timbres(msgs):
    """[(tick, channel, value), ...] for CC74 messages."""
    return [(t, m.channel, m.value) for t, m in msgs if m.type == 'control_change' and m.control == 74]


def rpns(msgs):
    """{channel: [(rpn, value), ...]} for the RPNs set in msgs (CC 101 / 100 / 6)."""
    out: dict[int, list] = {}
    selected: dict[int, tuple] = {}
    for _, m in msgs:
        if m.type != 'control_change':
            continue
        msb, lsb = selected.get(m.channel, (127, 127))
        if m.control == 101:
            selected[m.channel] = (m.value, lsb)
        elif m.control == 100:
            selected[m.channel] = (msb, m.value)
        elif m.control == 6:
            out.setdefault(m.channel, []).append((msb * 128 + lsb, m.value))
    return out


def test_mpe_strings_on_member_channels():
    assert string_channels(TRACK, MPE) == [6, 5, 4, 3, 2, 1]


def test_mpe_uses_channel_10():
    track = replace(TRACK, staves=[Staff(tuning=list(range(40, 50)))])
    assert string_channels(track, MPE) == [10, 9, 8, 7, 6, 5, 4, 3, 2, 1]


def test_mpe_single_channel_tracks():
    assert string_channels(replace(TRACK, is_drum=True), MPE) is None
    assert string_channels(replace(TRACK, staves=[Staff(tuning=list(range(40, 56)))]), MPE) is None


def test_mpe_configuration_message():
    assert rpns([(0, m) for m in mpe_configuration(6)]) == {0: [(6, 6)]}
    assert [(m.control, m.value) for m in mpe_configuration(6)][-2:] == [(101, 127), (100, 127)]


def test_mpe_header(tmp_path):
    msgs = convert(tmp_path, [{'string': 0}, {'string': 5}], mpe=True)
    set_rpns = rpns(msgs)
    # Zone of 6 members on the manager channel, bend range on every string channel
    assert set_rpns == {0: [(6, 6)], **{c: [(0, 12)] for c in range(1, 7)}}
    first_cc = next(i for i, (_, m) in enumerate(msgs) if m.type == 'control_change')
    assert msgs[first_cc][1].channel == 0                 # configuration before the bend ranges
    programs = [(m.channel, m.program) for _, m in msgs if m.type == 'program_change']
    assert programs == [(0, 29)]
    ons = [(m.channel, m.note) for _, m in msgs if m.type == 'note_on']
    assert ons == [(6, 47), (1, 71)]


def test_mpe_bend_on_its_string_only(tmp_path):
    msgs = convert(tmp_path, [{'string': 3, 'bend': BEND}, {'string': 4}], chords=[[0, 1]], mpe=True)
    pw = by_channel(msgs, 'pitchwheel')
    assert set(pw) == {3}
    assert pw[3][-1][1].pitch == 0


def test_mpe_on_drum_track_is_plain_midi(tmp_path):
    msgs = convert(tmp_path, [{}], track=replace(TRACK, is_drum=True), mpe=True)
    assert not any(m.type == 'control_change' for _, m in msgs)
    assert {m.channel for _, m in msgs if m.type == 'note_on'} == {9}


def test_mpe_timbre_marks_palm_muting(tmp_path):
    msgs = convert(tmp_path, [{'string': 0, 'palm_muted': True}, {'string': 5}], chords=[[0, 1]], mpe=True,
                   palm_mute_chords=False)
    assert sorted(timbres(msgs)) == [(0, 1, 0), (0, 6, 127)]
    # Each timbre comes before its channel's note-on
    for channel in (1, 6):
        order = [m.type for _, m in msgs if getattr(m, 'channel', None) == channel and
                 (m.type == 'note_on' or (m.type == 'control_change' and m.control == 74))]
        assert order == ['control_change', 'note_on']


def test_mpe_timbre_switches(tmp_path):
    msgs = convert(tmp_path, [{'palm_muted': True}, {}], mpe=True, open_timbre=64, palm_mute_timbre=100)
    assert [v for _, _, v in timbres(msgs)] == [100, 64]


def test_mpe_timbre_sent_only_on_change(tmp_path):
    # Three muted notes then an open one on string 2, and a tied continuation
    pm = {'palm_muted': True}
    msgs = convert(tmp_path, [pm, pm, {**pm, 'is_tie_dest': True}, {}], mpe=True)
    assert [(t, v) for t, _, v in timbres(msgs)] == [(0, 127), (3 * BEAT, 0)]


def test_mpe_timbre_moves_with_strum(tmp_path):
    from conftest import ScriptedRandom
    msgs = convert(tmp_path, [{'string': 0}, {'string': 5}], chords=[[0, 1]], mpe=True,
                   humanize=True, velocity_spread=0, rng=ScriptedRandom([]))
    on_tick = {m.channel: t for t, m in msgs if m.type == 'note_on'}
    assert {c: t for t, c, _ in timbres(msgs)} == on_tick
    assert on_tick[1] > on_tick[6]                     # downstroke: low string first


def test_no_timbre_without_mpe(tmp_path):
    msgs = convert(tmp_path, [{'palm_muted': True}], channel_per_string=True)
    assert timbres(msgs) == []


def test_drop_redundant_timbre():
    cc = lambda ch, v: (0, 1, Message('control_change', channel=ch, control=74, value=v))
    events = [cc(1, 0), cc(1, 0), cc(2, 0), cc(1, 127), cc(1, 127)]
    assert [(e[2].channel, e[2].value) for e in drop_redundant_timbre(events)] == [(1, 0), (2, 0), (1, 127)]


def test_mpe_timbre_mutes_whole_chord(tmp_path):
    msgs = convert(tmp_path, [{'string': 0, 'palm_muted': True}, {'string': 5}], chords=[[0, 1]], mpe=True)
    assert sorted(timbres(msgs)) == [(0, 1, 127), (0, 6, 127)]
