import argparse
import queue
import subprocess
import sys
import threading

from .captions import CaptionEngine, SAMPLE_RATE
from .linux_audio import capture_process, playback_streams, vrchat_stream
from .server import CaptionServer, load_config


def capture_loop(source, engine, config, done, finite, print_captions):
    size = config["chunk_seconds"] * SAMPLE_RATE * 2
    chunks = queue.Queue(maxsize=1)

    def read_audio():
        try:
            while not done.is_set() and (pcm := source.read(size)):
                if finite:
                    chunks.put(pcm)
                else:
                    try:
                        chunks.put_nowait(pcm)
                    except queue.Full:
                        try:
                            chunks.get_nowait()
                        except queue.Empty:
                            pass
                        chunks.put_nowait(pcm)
        finally:
            chunks.put(None)

    threading.Thread(target=read_audio, daemon=True).start()
    while not done.is_set():
        try:
            pcm = chunks.get(timeout=0.5)
        except queue.Empty:
            continue
        if pcm is None:
            print("Audio input ended.", flush=True)
            done.set()
            return
        if len(pcm) < SAMPLE_RATE or len(pcm) % 2:
            continue
        try:
            captions = engine.transcribe(pcm, config["language"], config["mode"])
        except BlockingIOError:
            continue
        except Exception as error:
            print(f"Transcription failed: {error}", file=sys.stderr)
            done.set()
            return
        if not print_captions:
            continue
        for caption in captions:
            speaker = f'Speaker {caption["speaker"]}' if caption["speaker"] else "Unassigned"
            print(f'{speaker} [{caption["language"]}] {caption["text"]}', flush=True)


def main():
    parser = argparse.ArgumentParser(description="WiVRn Translations")
    parser.add_argument("--config", help="Path to the companion JSON settings")
    parser.add_argument("--speakers", metavar="MODEL_DIRECTORY", help="Enable speaker diarization")
    display = parser.add_mutually_exclusive_group()
    display.add_argument("--wayvr", action="store_true", help="Show non-English speech translated to English in the WiVRn overlay")
    display.add_argument("--steamvr", action="store_true", help="Display captions in the SteamVR compositor")
    audio = parser.add_mutually_exclusive_group()
    audio.add_argument("--list-streams", action="store_true", help="List Linux playback stream IDs")
    audio.add_argument("--vrchat", action="store_true", help="Find and capture the VRChat playback stream on Linux")
    audio.add_argument("--stream", type=int, metavar="INDEX", help="Capture one Linux playback stream")
    audio.add_argument("--monitor", metavar="SOURCE", help="Capture a Linux sink monitor, e.g. @DEFAULT_MONITOR@")
    audio.add_argument("--pcm-stdin", action="store_true", help="Read 16 kHz mono s16le PCM on stdin")
    args = parser.parse_args()

    process = None
    capture_worker = None
    stopped = threading.Event()
    try:
        if args.list_streams:
            playback_streams()
            return 0
        stream = vrchat_stream() if args.vrchat else args.stream
        config, token = load_config(args.config)
        tracker = None
        if args.speakers:
            from .speakers import SpeakerTracker
            tracker = SpeakerTracker(args.speakers)
        engine = CaptionEngine(config["model"], tracker, translate_non_english=args.wayvr)
        overlay = None
        wayvr = None
        if args.steamvr:
            from .steamvr import SteamOverlay
            overlay = SteamOverlay()
        try:
            host_audio = stream is not None or bool(args.monitor) or args.pcm_stdin
            with CaptionServer(config["host"], config["port"], engine, token, host_audio) as server:
                if args.wayvr:
                    from .wayvr import WayVROverlay
                    wayvr = WayVROverlay(config["port"])
                server_thread = threading.Thread(target=server.serve_forever, daemon=True)
                server_thread.start()
                print(f'Caption monitor port {config["port"]} (local browser: http://127.0.0.1:{config["port"]})', flush=True)
                if stream is not None or args.monitor:
                    process = capture_process(stream, args.monitor)
                source = process.stdout if process else sys.stdin.buffer if args.pcm_stdin else None
                if source:
                    capture_worker = threading.Thread(
                        target=capture_loop,
                        args=(source, engine, config, stopped, args.pcm_stdin, not args.wayvr),
                        daemon=True,
                    )
                    capture_worker.start()
                try:
                    while not stopped.wait(0.2):
                        if overlay:
                            overlay.update(engine.current())
                        if process and process.poll() is not None:
                            raise RuntimeError(f"Linux audio capture exited with status {process.returncode}.")
                finally:
                    stopped.set()
                    server.shutdown()
                    server_thread.join()
        finally:
            if overlay:
                overlay.close()
            if wayvr:
                wayvr.close()
    except KeyboardInterrupt:
        pass
    except (OSError, ValueError, RuntimeError, ImportError) as error:
        print(f"WiVRn Translations: {error}", file=sys.stderr)
        return 1
    finally:
        stopped.set()
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if capture_worker:
            capture_worker.join()
    return 0


if __name__ == "__main__":
    sys.exit(main())
