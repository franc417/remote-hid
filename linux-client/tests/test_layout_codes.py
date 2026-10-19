"""The Android layouts and the desktop key map must agree: a key the phone can send that the
desktop does not know would look right on screen and silently do nothing."""

import glob
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import input_backend  # noqa: E402

DOCS = os.path.join(os.path.dirname(__file__), "..", "..", "android-app", "docs")
TEMPLATES = sorted(glob.glob(os.path.join(DOCS, "keyboard-layout.*.txt")))

# What fn turns keys into (FnMap in KeyboardLayout.kt).
FN_TARGETS = ["F%d" % i for i in range(1, 13)] + ["Home", "PageUp", "PageDown", "End"]
SPECIAL = {"shift", "ctrl", "alt", "fn", "spacer", "unicode"}


def split_fields(token):
    """Splits a key token on `|`, skipping a character after each backslash exactly as the
    Kotlin parser does (so a label of one backslash, written \\\\, does not hide the separator)."""
    fields, current, i = [], [], 0
    while i < len(token):
        c = token[i]
        if c == "\\" and i + 1 < len(token):
            current.append(token[i:i + 2])
            i += 2
        elif c == "|":
            fields.append("".join(current))
            current = []
            i += 1
        else:
            current.append(c)
            i += 1
    fields.append("".join(current))
    return fields


def codes_in(path):
    codes = []
    for raw in open(path, encoding="utf-8"):
        line = raw.strip()
        if not line.startswith("row "):
            continue
        for token in line.split()[2:]:
            codes.append(split_fields(token)[1])
    return codes


def test_the_tokenizer_handles_escaped_labels():
    assert split_fields("\\\\|Backslash") == ["\\\\", "Backslash"]            # label is one backslash
    assert split_fields("\\||Backslash|1.0|shift") == ["\\|", "Backslash", "1.0", "shift"]  # label is a pipe
    assert split_fields("q|KeyQ") == ["q", "KeyQ"]


def test_the_templates_exist():
    assert len(TEMPLATES) >= 2, TEMPLATES


@pytest.mark.parametrize("path", TEMPLATES, ids=os.path.basename)
def test_every_key_in_the_layout_is_known_to_the_desktop(path):
    unknown = [c for c in codes_in(path)
               if c not in input_backend.KEY_MAP and c not in SPECIAL and not c.startswith("layer:")]
    assert unknown == []


def test_every_fn_target_is_known_to_the_desktop():
    assert [c for c in FN_TARGETS if c not in input_backend.KEY_MAP] == []


@pytest.mark.parametrize("path", TEMPLATES, ids=os.path.basename)
def test_the_templates_have_no_separate_fn_page(path):
    text = open(path, encoding="utf-8").read()
    assert "layer fn" not in text and "layer:fn" not in text


def test_every_modifier_name_the_phone_sends_is_known_to_the_desktop():
    assert all(m in input_backend.MOD_MAP for m in ("shift", "ctrl", "alt", "meta"))


def test_fn_targets_reach_real_kernel_keys():
    evdev = pytest.importorskip("evdev")
    for code in FN_TARGETS + ["Escape", "PrintScreen"]:
        assert hasattr(evdev.ecodes, input_backend.KEY_MAP[code]), code
