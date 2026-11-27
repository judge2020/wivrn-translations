import hmac
import ipaddress
import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .captions import SAMPLE_RATE


MAX_AUDIO = SAMPLE_RATE * 2 * 6
LANGUAGE = re.compile(r"auto|[a-z]{2,3}")
TOKEN = re.compile(r"[a-fA-F0-9]{32,128}")
MONITOR = Path(__file__).with_name("monitor.html")


class CaptionServer(ThreadingHTTPServer):
    def __init__(self, host, port, engine, token, host_audio=False):
        super().__init__((host, port), CaptionHandler)
        self.engine = engine
        self.token = token
        self.host_audio = host_audio


class CaptionHandler(BaseHTTPRequestHandler):
    def setup(self):
        self.request.settimeout(15)
        super().setup()

    def log_message(self, *_args):
        pass

    def respond(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def json(self, status, value):
        self.respond(status, json.dumps(value, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def authorized(self):
        token = self.server.token
        header = self.headers.get("Authorization", "").encode("latin-1")
        return bool(token and hmac.compare_digest(header, f"Bearer {token}".encode()))

    def do_GET(self):
        if self.path == "/health":
            self.json(200, {"version": 1, "status": "ready"})
        elif self.path in ("/", "/overlay", "/v1/latest"):
            host = self.headers.get("Host", "").split(":", 1)[0]
            local = ipaddress.ip_address(self.client_address[0]).is_loopback and host in {"127.0.0.1", "localhost"}
            if self.path in ("/", "/overlay") and local:
                self.respond(200, MONITOR.read_bytes(), "text/html; charset=utf-8")
            elif self.path == "/v1/latest" and (local or self.authorized()):
                self.json(200, {"version": 1, "captions": self.server.engine.current()})
            else:
                self.json(401, {"error": "Use the local monitor or provide the companion token."})
        else:
            self.json(404, {"error": "Unknown endpoint."})

    def do_POST(self):
        if self.path != "/v1/audio":
            self.json(404, {"error": "Unknown endpoint."})
            return
        if not self.authorized():
            self.json(401, {"error": "Check the companion token."})
            return
        if self.server.host_audio:
            self.json(409, {"error": "The companion is already capturing audio. Use Monitor companion."})
            return
        if self.headers.get_content_type() != "application/octet-stream":
            self.json(415, {"error": "Send raw 16 kHz mono PCM signed 16-bit little endian."})
            return
        length = self.headers.get("Content-Length", "")
        if not re.fullmatch(r"[0-9]{1,6}", length):
            self.json(411, {"error": "Send the audio byte count as Content-Length."})
            return
        size = int(length)
        if size < SAMPLE_RATE or size > MAX_AUDIO or size % 2:
            self.json(400, {"error": "Send 0.5 to 6 seconds of whole PCM samples."})
            return
        language = self.headers.get("X-Source-Language", "auto")
        mode = self.headers.get("X-Caption-Mode", "transcribe")
        if not LANGUAGE.fullmatch(language) or mode not in {"transcribe", "translate"}:
            self.json(400, {"error": "Invalid speech language or caption mode."})
            return
        pcm = self.rfile.read(size)
        if len(pcm) != size:
            self.json(400, {"error": "Incomplete audio chunk."})
            return
        try:
            captions = self.server.engine.transcribe(pcm, language, mode)
        except BlockingIOError:
            self.json(429, {"error": "Speech model busy."})
            return
        except ValueError:
            self.json(400, {"error": "Model does not support this source language or caption mode."})
            return
        except Exception as error:
            print(f"Speech model error: {error}", flush=True)
            self.json(500, {"error": "Speech model error. Check the companion terminal."})
            return
        self.json(200, {"version": 1, "captions": captions})


def load_config(path):
    config = {
        "host": "127.0.0.1",
        "port": 8765,
        "model": "base",
        "language": "auto",
        "mode": "transcribe",
        "chunk_seconds": 6,
    }
    if path:
        with open(path, encoding="utf-8") as stream:
            loaded = json.load(stream)
        if not isinstance(loaded, dict) or loaded.keys() - config.keys():
            raise ValueError("Config must be a JSON object with recognized settings.")
        config.update(loaded)

    host = config["host"]
    if not isinstance(host, str) or ipaddress.ip_address(host).version != 4:
        raise ValueError("host must be an IPv4 address.")
    if type(config["port"]) is not int or not 1 <= config["port"] <= 65535:
        raise ValueError("port must be an integer from 1 through 65535.")
    if type(config["chunk_seconds"]) is not int or not 2 <= config["chunk_seconds"] <= 6:
        raise ValueError("chunk_seconds must be an integer from 2 through 6.")
    if not isinstance(config["language"], str) or not LANGUAGE.fullmatch(config["language"]):
        raise ValueError("language must be auto or a lowercase Whisper language code.")
    if config["mode"] not in ("transcribe", "translate"):
        raise ValueError("mode must be transcribe or translate.")
    if not isinstance(config["model"], str) or not config["model"]:
        raise ValueError("model must be a Faster Whisper model name or path.")

    token = os.environ.get("SINGULARITY_TOKEN", "")
    if token and not TOKEN.fullmatch(token):
        raise ValueError("SINGULARITY_TOKEN must contain 32 to 128 hex characters.")
    if not ipaddress.ip_address(host).is_loopback and not token:
        raise ValueError("Set SINGULARITY_TOKEN before binding to the LAN.")
    return config, token
