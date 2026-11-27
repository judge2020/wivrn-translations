from ctypes import create_string_buffer
from pathlib import Path

import openvr
from PIL import Image, ImageDraw, ImageFont


COLORS = ("#bdf3d7", "#b8d9ff", "#ffe0a2", "#fbcaf1", "#dcd1ff", "#ffc4ab")
FONT_PATHS = (
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/google-noto-sans-cjk-vf-fonts/NotoSansCJK-VF.ttc",
    "C:/Windows/Fonts/msyh.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
)


def text_font(size):
    for name in FONT_PATHS:
        if Path(name).exists():
            return ImageFont.truetype(name, size)
    return ImageFont.load_default(size=size)


def wrap(draw, text, font, width):
    line = ""
    for char in text:
        if line and draw.textlength(line + char, font=font) > width:
            before, split, after = line.rpartition(" ")
            if split:
                yield before
                line = after + char
                continue
            yield line
            line = ""
        line += char
    if line.strip():
        yield line.strip()


class SteamOverlay:
    def __init__(self):
        openvr.init(openvr.VRApplication_Overlay)
        try:
            self.overlay = openvr.IVROverlay()
            self.handle = self.overlay.createOverlay("sh.judge.singularity", "Singularity")
            self.overlay.setOverlayWidthInMeters(self.handle, 0.9)
            transform = openvr.HmdMatrix34_t()
            for row, values in zip(transform.m, ((1, 0, 0, 0), (0, 1, 0, -0.32), (0, 0, 1, -1.15))):
                row[:] = values
            self.overlay.setOverlayTransformTrackedDeviceRelative(
                self.handle, openvr.k_unTrackedDeviceIndex_Hmd, transform
            )
        except Exception:
            openvr.shutdown()
            raise
        self.previous = ()
        self.font = text_font(44)
        self.label_font = text_font(27)

    def update(self, captions):
        captions = captions[-3:]
        ids = tuple(row["id"] for row in captions)
        if ids == self.previous:
            return
        self.previous = ids
        if not ids:
            self.overlay.hideOverlay(self.handle)
            return
        panel = Image.new("RGBA", (1536, 512), (0, 0, 0, 0))
        draw = ImageDraw.Draw(panel)
        y = 12
        for caption in captions:
            speaker = caption["speaker"]
            if speaker:
                label = f"Speaker {speaker}"
                color = COLORS[(speaker - 1) % len(COLORS)]
            else:
                label = "Overlapping speech" if caption["kind"] == "overlap" else "Speech"
                color = "#becdc3"
            lines = list(wrap(draw, caption["text"], self.font, 1480))
            if len(lines) > 2:
                lines = [lines[0], lines[1][:-2] + "…"]
            height = 53 + 50 * len(lines)
            draw.rounded_rectangle((8, y, 1528, y + height), 14, fill=(14, 23, 19, 235))
            draw.rectangle((18, y + 9, 23, y + height - 9), fill=color)
            draw.text((38, y + 9), label, font=self.label_font, fill=color)
            for index, line in enumerate(lines):
                draw.text((38, y + 40 + index * 50), line, font=self.font, fill="white")
            y += height + 8
        pixels = create_string_buffer(panel.tobytes())
        self.overlay.setOverlayRaw(self.handle, pixels, panel.width, panel.height, 4)
        self.overlay.showOverlay(self.handle)

    def close(self):
        try:
            self.overlay.destroyOverlay(self.handle)
        finally:
            openvr.shutdown()
