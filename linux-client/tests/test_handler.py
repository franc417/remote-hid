import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from handler import handle_message
from input_backend import MockBackend


def test_move():
    backend = MockBackend()
    handle_message({"t": "move", "dx": 5, "dy": -3}, backend)
    assert backend.calls == [("move", 5, -3)]


def test_click_defaults_to_left_click():
    backend = MockBackend()
    handle_message({"t": "click"}, backend)
    assert backend.calls == [("click", "left", "click")]


def test_click_down_up_for_drag():
    backend = MockBackend()
    handle_message({"t": "click", "action": "down"}, backend)
    handle_message({"t": "move", "dx": 3, "dy": 0}, backend)
    handle_message({"t": "click", "action": "up"}, backend)
    assert backend.calls == [
        ("click", "left", "down"),
        ("move", 3, 0),
        ("click", "left", "up"),
    ]


def test_scroll():
    backend = MockBackend()
    handle_message({"t": "scroll", "dy": -2}, backend)
    assert backend.calls == [("scroll", -2)]


def test_key_with_modifiers():
    backend = MockBackend()
    handle_message({"t": "key", "code": "KeyV", "action": "down", "mods": ["ctrl"]}, backend)
    assert backend.calls == [("key", "KeyV", "down", ("ctrl",))]


def test_key_without_mods_field_defaults_to_empty():
    backend = MockBackend()
    handle_message({"t": "key", "code": "Enter", "action": "down"}, backend)
    assert backend.calls == [("key", "Enter", "down", ())]


def test_malformed_number_is_dropped_not_raised():
    backend = MockBackend()
    handle_message({"t": "move", "dx": "not a number", "dy": 1}, backend)
    assert backend.calls == []


def test_bool_is_not_accepted_as_a_number():
    # bool is a subclass of int in Python — make sure True/False don't
    # sneak through _require_number as if they were 1/0.
    backend = MockBackend()
    handle_message({"t": "move", "dx": True, "dy": 1}, backend)
    assert backend.calls == []


def test_unknown_message_type_is_dropped():
    backend = MockBackend()
    handle_message({"t": "explode"}, backend)
    assert backend.calls == []


def test_invalid_button_is_dropped():
    backend = MockBackend()
    handle_message({"t": "click", "button": "fourth"}, backend)
    assert backend.calls == []


def test_invalid_modifier_is_dropped():
    backend = MockBackend()
    handle_message({"t": "key", "code": "KeyA", "action": "down", "mods": ["banana"]}, backend)
    assert backend.calls == []


def test_non_dict_message_is_dropped():
    backend = MockBackend()
    handle_message("not a dict", backend)
    assert backend.calls == []
