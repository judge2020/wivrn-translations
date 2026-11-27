"""Transparent GTK window hosted by WayVR's Wayland compositor."""

import json
from pathlib import Path
import sys
import threading
import urllib.request

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango


COLORS = ("#bdf3d7", "#b8d9ff", "#ffe0a2", "#fbcaf1", "#dcd1ff", "#ffc4ab")
CSS = """
window.caption-window {
    background: transparent;
    border: none;
    box-shadow: none;
}
.caption-row {
    background-color: rgba(12, 20, 16, 0.66);
    border-radius: 12px;
    padding: 6px 14px 8px;
}
.speaker-label { font-size: 16px; font-weight: bold; color: #becdc3; }
.caption-text { font-size: 27px; color: white; }
""" + "\n".join(f".speaker-{i} {{ color: {color}; }}" for i, color in enumerate(COLORS))


def language_names():
    try:
        data = Path("/usr/share/iso-codes/json/iso_639-3.json").read_text(encoding="utf-8")
    except OSError:
        return {}
    return {
        entry[key]: entry.get("common_name", entry["name"])
        for entry in json.loads(data)["639-3"]
        for key in ("alpha_2", "alpha_3")
        if key in entry
    }


class CaptionPanel(Gtk.Application):
    def __init__(self, port):
        super().__init__(
            application_id="sh.judge.singularity.panel", flags=Gio.ApplicationFlags.NON_UNIQUE,
        )
        self.url = f"http://127.0.0.1:{port}/v1/latest"
        self.stopped = threading.Event()
        self.languages = language_names()

    def do_activate(self):
        if self.get_active_window():
            self.get_active_window().present()
            return
        window = Gtk.ApplicationWindow(application=self, title="WiVRn Translations")
        window.set_default_size(960, 340)
        window.set_decorated(False)
        window.add_css_class("caption-window")
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS.encode())
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        self.rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.rows.set_valign(Gtk.Align.END)
        self.rows.set_margin_start(12)
        self.rows.set_margin_end(12)
        self.rows.set_margin_bottom(12)
        window.set_child(self.rows)
        window.present()
        threading.Thread(target=self.poll, daemon=True).start()

    def poll(self):
        previous = None
        while not self.stopped.is_set():
            try:
                with urllib.request.urlopen(self.url, timeout=1) as response:
                    captions = json.load(response)["captions"]
            except (OSError, ValueError, KeyError):
                captions = []
            group = {}
            for caption in captions:
                key = caption["speaker"] or caption["kind"]
                group[key] = caption
            latest = sorted(group.values(), key=lambda row: row["id"])[-3:]
            if latest != previous:
                GLib.idle_add(self.render, latest)
                previous = latest
            self.stopped.wait(0.35)

    def render(self, captions):
        while child := self.rows.get_first_child():
            self.rows.remove(child)
        for caption in captions:
            speaker = caption["speaker"]
            name = f"Speaker {speaker}" if speaker else (
                "Overlapping speech" if caption["kind"] == "overlap" else "Speech"
            )
            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            row.set_halign(Gtk.Align.CENTER)
            row.add_css_class("caption-row")

            code = caption["language"]
            language = self.languages.get(code, code.upper())
            heading = Gtk.Label(label=f"{name} · {language}", xalign=0.0)
            heading.add_css_class("speaker-label")
            if speaker:
                heading.add_css_class(f"speaker-{(speaker - 1) % len(COLORS)}")
            row.append(heading)

            text = Gtk.Label(label=caption["text"], xalign=0.0)
            text.add_css_class("caption-text")
            text.set_max_width_chars(52)
            text.set_wrap(True)
            text.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
            text.set_lines(2)
            text.set_ellipsize(Pango.EllipsizeMode.END)
            row.append(text)
            self.rows.append(row)

    def do_shutdown(self):
        self.stopped.set()
        Gtk.Application.do_shutdown(self)


if __name__ == "__main__":
    sys.exit(CaptionPanel(int(sys.argv[1])).run([sys.argv[0]]))
