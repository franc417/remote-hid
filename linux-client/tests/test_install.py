"""install.sh: puts a working `remote-hid` command and menu entry under a (temporary) HOME."""

import configparser
import os
import stat
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
INSTALL = os.path.join(HERE, "..", "install.sh")

pytestmark = pytest.mark.skipif(
    subprocess.run(["bash", "-c", "true"], capture_output=True).returncode != 0, reason="needs bash"
)


def run(home, *args, env_extra=None):
    env = {"PATH": os.environ["PATH"], "HOME": str(home)}
    env.update(env_extra or {})
    return subprocess.run(["bash", INSTALL, *args], capture_output=True, text=True, env=env, timeout=30)


def fake_python(tmp_path):
    """A stand-in interpreter that just prints what it was asked to run."""
    p = tmp_path / "fakepy"
    p.write_text('#!/bin/sh\nif [ "$1" = "-" ]; then cat >/dev/null; echo ""; exit 0; fi\necho "RAN $@"\n')
    p.chmod(0o755)
    return str(p)


def test_installs_a_launcher_menu_entry_and_icon(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    r = run(home, "--python", sys.executable)
    assert r.returncode == 0, r.stderr
    launcher = home / ".local" / "bin" / "remote-hid"
    assert launcher.exists() and launcher.stat().st_mode & stat.S_IXUSR
    assert sys.executable in launcher.read_text()                 # the chosen python is baked in
    assert os.path.abspath(os.path.join(HERE, "..", "gui.py")) in launcher.read_text()
    entry = home / ".local" / "share" / "applications" / "remote-hid.desktop"
    cfg = configparser.ConfigParser()
    cfg.read(entry)
    assert cfg["Desktop Entry"]["Exec"] == str(launcher)
    assert cfg["Desktop Entry"]["Icon"] == "remote-hid"
    assert (home / ".local" / "share" / "icons" / "hicolor" / "256x256" / "apps" / "remote-hid.png").exists()


def test_the_launcher_runs_gui_py_with_the_baked_python_and_passes_arguments(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    py = fake_python(tmp_path)
    assert run(home, "--python", py).returncode == 0
    out = subprocess.run([str(home / ".local" / "bin" / "remote-hid"), "one", "two words"], capture_output=True, text=True)
    assert out.returncode == 0
    assert out.stdout.startswith("RAN ") and "gui.py" in out.stdout
    assert out.stdout.strip().endswith("one two words")


def test_a_missing_python_is_a_clear_error_and_installs_nothing(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    r = run(home, "--python", str(tmp_path / "nope"))
    assert r.returncode != 0
    assert "--python" in r.stderr
    assert not (home / ".local" / "bin" / "remote-hid").exists()


def test_missing_packages_are_reported_but_do_not_block_the_install(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    p = tmp_path / "py-missing"
    p.write_text('#!/bin/sh\nif [ "$1" = "-" ]; then cat >/dev/null; echo "evdev, qrcode"; exit 0; fi\n')
    p.chmod(0o755)
    r = run(home, "--python", str(p))
    assert r.returncode == 0
    assert "missing: evdev, qrcode" in r.stderr
    assert (home / ".local" / "bin" / "remote-hid").exists()


def test_the_active_virtualenv_is_preferred(tmp_path):
    home = tmp_path / "home"
    (tmp_path / "venv" / "bin").mkdir(parents=True)
    vpy = tmp_path / "venv" / "bin" / "python"
    vpy.write_text('#!/bin/sh\nif [ "$1" = "-" ]; then cat >/dev/null; echo ""; exit 0; fi\n')
    vpy.chmod(0o755)
    home.mkdir()
    assert run(home, env_extra={"VIRTUAL_ENV": str(tmp_path / "venv")}).returncode == 0
    assert str(vpy) in (home / ".local" / "bin" / "remote-hid").read_text()


def test_running_it_twice_just_refreshes(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    assert run(home, "--python", sys.executable).returncode == 0
    other = fake_python(tmp_path)
    assert run(home, "--python", other).returncode == 0
    text = (home / ".local" / "bin" / "remote-hid").read_text()
    assert other in text and sys.executable not in text


def test_uninstall_removes_exactly_what_was_installed(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    keep = home / ".local" / "bin" / "other-tool"
    keep.parent.mkdir(parents=True)
    keep.write_text("keep me")
    run(home, "--python", sys.executable)
    r = run(home, "--uninstall")
    assert r.returncode == 0
    assert not (home / ".local" / "bin" / "remote-hid").exists()
    assert not (home / ".local" / "share" / "applications" / "remote-hid.desktop").exists()
    assert keep.read_text() == "keep me"


def test_it_tells_you_when_the_bin_directory_is_not_on_path(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    r = run(home, "--python", sys.executable)
    assert ".local/bin" in r.stdout and ("Add" in r.stdout or "Run it with" in r.stdout)


def test_a_bad_option_is_rejected(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    assert run(home, "--bogus").returncode == 2
