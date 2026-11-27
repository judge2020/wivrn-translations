import json
import subprocess


def pulse_list(kind):
    return json.loads(subprocess.check_output(["pactl", "--format=json", "list", kind]))


def playback_streams():
    for stream in pulse_list("sink-inputs"):
        properties = stream["properties"]
        name = properties.get("application.name", "Unknown application")
        media = properties.get("media.name", "")
        print(f'{stream["index"]:>6}  {name}  {media}')


def vrchat_stream():
    matches = [
        stream["index"] for stream in pulse_list("sink-inputs")
        if any(
            stream["properties"].get(key, "").casefold() in {"vrchat", "vrchat.exe"}
            for key in ("application.name", "application.process.binary")
        )
    ]
    if len(matches) != 1:
        raise ValueError("Expected one VRChat playback stream. Run --list-streams and specify --stream INDEX.")
    return matches[0]


def capture_process(stream_index, monitor):
    command = ["parec", "--raw", "--format=s16le", "--channels=1", "--rate=16000", "--latency-msec=100"]
    if stream_index is not None:
        streams = {stream["index"]: int(stream["sink"]) for stream in pulse_list("sink-inputs")}
        monitors = {sink["index"]: sink["monitor_source"] for sink in pulse_list("sinks")}
        if stream_index not in streams or not monitors.get(streams[stream_index]):
            raise ValueError("Playback stream has no monitor. Run --list-streams while VRChat is playing.")
        command.extend([f"--monitor-stream={stream_index}", f"--device={monitors[streams[stream_index]]}"])
    else:
        command.append(f"--device={monitor}")
    return subprocess.Popen(command, stdout=subprocess.PIPE)
