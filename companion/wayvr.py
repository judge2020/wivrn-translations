"""Host the caption window in WayVR's OpenXR compositor overlay."""

import json
from pathlib import Path
import shlex
import shutil
import subprocess


class WayVROverlay:
    def __init__(self, port):
        self.control = shutil.which("wayvrctl")
        if not self.control:
            raise RuntimeError("Install WayVR and start it with WiVRn before using --wayvr.")

        # The GTK bindings installed by Linux distributions use the system Python.
        python = "/usr/bin/python3"
        try:
            subprocess.run(
                [python, "-c", "import gi; gi.require_version('Gtk', '4.0'); from gi.repository import Gtk"],
                check=True, capture_output=True, timeout=5,
            )
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            raise RuntimeError("Install Python's GObject bindings and GTK 4 for the WayVR panel.") from error

        panel = Path(__file__).with_name("wayvr_panel.py").resolve()
        response = self.call(
            "process-launch", "--name", "WiVRn Translations",
            "--env", "GDK_BACKEND=wayland,GSK_RENDERER=cairo",
            python, "960x340", "floating", "", "--", shlex.join([str(panel), str(port)]),
        )
        self.handle = json.loads(response)
        if not isinstance(self.handle, dict) or "user" not in self.handle:
            raise ValueError("WayVR did not return a caption window process handle.")

    def call(self, *arguments):
        try:
            return subprocess.run(
                [self.control, *arguments], check=True, text=True, capture_output=True, timeout=10,
            ).stdout
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            raise RuntimeError("Could not contact WayVR. Check that it is running inside WiVRn.") from error

    def close(self):
        try:
            self.call("process-terminate", json.dumps(self.handle, separators=(",", ":")))
        except RuntimeError:
            pass
