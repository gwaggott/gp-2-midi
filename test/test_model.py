"""Tests for gpif/model.py: raw XML access (element, properties) and equality."""

import xml.etree.ElementTree as ET
from dataclasses import FrozenInstanceError

import pytest

from gpif import Beat, Note, property_value

NOTE_XML = '''<Note id="0"><LetRing/><Properties>
  <Property name="Fret"><Fret> 7 </Fret></Property>
  <Property name="Muted"><Enable/></Property>
  <Property name="ConcertPitch"><Pitch><Step>A</Step><Octave>3</Octave></Pitch></Property>
</Properties></Note>'''


@pytest.mark.parametrize('xml, expected', [
    ('<Property name="Fret"><Fret> 7 </Fret></Property>', '7'),
    ('<Property name="Muted"><Enable/></Property>', ''),                # flag
    ('<Property name="P"><Pitch><Step>A</Step></Pitch></Property>', ''),  # structured
    ('<Property name="Empty"/>', ''),
])
def test_property_value(xml, expected):
    assert property_value(ET.fromstring(xml)) == expected


def test_properties_from_element():
    note = Note(fret=7, element=ET.fromstring(NOTE_XML))
    assert note.properties == {'Fret': '7', 'Muted': '', 'ConcertPitch': ''}
    assert note.properties is note.properties                 # computed once
    assert note.element.find('LetRing') is not None           # child elements via element


def test_properties_without_element_are_empty():
    assert Note().properties == {}
    assert Beat().properties == {}


def test_raw_fields_left_out_of_equality_and_repr():
    note = Note(fret=7, element=ET.fromstring(NOTE_XML))
    note.properties                                           # fill the cache
    assert note == Note(fret=7)
    assert 'element' not in repr(note) and 'properties' not in repr(note)


def test_still_frozen():
    note = Note(element=ET.fromstring(NOTE_XML))
    with pytest.raises(FrozenInstanceError):
        note.fret = 3
