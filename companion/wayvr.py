"""Open the local caption monitor inside WayVR's OpenXR compositor overlay."""

import json
import shlex
import shutil
import subprocess
from tempfile import TemporaryDirectory


class WayVROverlay:
    def __init__(self, port):
        self.control = shutil.which("wayvrctl")
        if not self.control:
            raise RuntimeError("Install WayVR and start it with WiVRn before using --wayvr.")
        browser = next(
            (path for name in ("google-chrome", "chromium", "chromium-browser", "brave-browser")
             if (path := shutil.which(name))),
            None,
        )
        if not browser:
            raise RuntimeError("Install a native Chrome or Chromium browser for the WayVR caption window.")

        self.profile = TemporaryDirectory(prefix="vrchat-captions-wayvr-")
        arguments = shlex.join([
            "--ozone-platform=wayland",
            "--disable-background-mode",
            "--no-first-run",
            "--no-default-browser-check",
            f"--user-data-dir={self.profile.name}",
            f"--app=http://127.0.0.1:{port}/overlay",
        ])
        try:
            response = self.call(
                "process-launch", "--name", "VRChat Live Captions",
                browser, "1120x460", "floating", "", "--", arguments,
            )
            self.handle = json.loads(response)
            if not isinstance(self.handle, dict) or "user" not in self.handle:
                raise ValueError("WayVR did not return a browser process handle.")
        except Exception:
            self.profile.cleanup()
            raise

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
        finally:
            self.profile.cleanup()
