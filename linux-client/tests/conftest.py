import os

# The real accessibility backend needs a desktop session; tests that want field
# mirroring install a fake watcher explicitly (see test_fieldwatch.py).
os.environ.setdefault("REMOTE_HID_NO_FIELD", "1")
