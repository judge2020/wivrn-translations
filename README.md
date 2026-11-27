# Singularity

Singularity captions incoming VRChat audio. The Linux companion runs multilingual
speech recognition and optional speaker diarization locally. Its browser monitor
and Android/Quest panel group captions into separate, color-coded speaker rows.
A head-locked SteamVR overlay shows the latest three turns.

## Linux · capture VRChat playback

Start VRChat and let it play audio. On the Linux host, install Python 3.12 and the
PulseAudio client utilities (`pactl` and `parec`). The same commands work with
PipeWire-Pulse if your session exposes the VRChat playback stream.

```sh
git clone https://github.com/judge2020/singularity.git
cd singularity
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r requirements-speakers.txt
mkdir -p models
curl -fL https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2 |
  tar -xj -C models
curl -fL https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx   -o models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx
```

The first run downloads the multilingual Whisper `base` model. Browse to
[the local monitor](http://127.0.0.1:8765).

```sh
python -m companion --vrchat --speakers models
```

If automatic stream selection fails, run `python -m companion --list-streams`
and pass `--stream INDEX` in place of `--vrchat`. Restart the companion after
VRChat recreates its playback stream.

If your audio server cannot monitor one stream, you can select the VR headset's
sink monitor using `pactl list short sources` and pass its name to
`--monitor` instead of `--stream`. That captures everything played to that
sink, including other apps. `--pcm-stdin` accepts an external audio source as
16 kHz mono signed 16-bit little-endian PCM.

Copy [config.example.json](config.example.json) to `config.json` and add
`--config config.json` to change settings. `language` can be `auto` or a source
code such as `ja` or `es`. Use `"mode": "translate"` for English captions, or
`"mode": "transcribe"` to preserve the spoken language. Captions arrive in
batches of up to six seconds, plus inference time. Smaller chunks trade
speaker and speech accuracy for responsiveness. If processing falls behind,
live capture prioritizes the newest audio.

## Display in VR

### SteamVR

With SteamVR running, add `--steamvr` to the Linux command:

```sh
pip install -r requirements-steamvr.txt
python -m companion --vrchat --speakers models --steamvr
```

VRChat must be visible through the SteamVR compositor for the head-locked
panel to appear. For CJK caption glyphs, install your distro's Noto Sans CJK
fonts. Direct OpenXR runtimes such as WiVRn without SteamVR can use the
desktop monitor or the Quest panel where Horizon OS permits multitasking.

### Android / Quest Pro panel

1. Download the APK from [Releases](https://github.com/judge2020/singularity/releases).
   Sideload it in developer mode with `adb install singularity-0.1.0.apk` and
   launch **Singularity** from Unknown Sources. The app uses standard Android
   APIs and requires no root privileges.
2. Copy `config.example.json` to `config.json`, set `host` to `0.0.0.0`, and set
   a companion token with `export SINGULARITY_TOKEN="$(openssl rand -hex 32)"`.
   Run the Linux command again with `--config config.json`. Keep both devices
   on the same trusted network. Plain HTTP on the LAN carries the audio,
   captions and token. For encrypted transport use an HTTPS reverse proxy.
3. Enter `http://<Linux-host-IP>:8765` and the token in the Android app. Select
   **Monitor companion** to view captions from Linux. Horizon OS owns the
   placement and visibility of the 2D panel while VRChat is immersive.

For standalone VRChat running on the headset itself, start
`python -m companion --config config.json --speakers models` without a Linux
audio source. In the APK, choose **Capture VRChat playback** and accept the
Android playback sharing prompt. If offered a choice, select the entire
display. Singularity requests an audio-only stream limited to VRChat's app
UID, with no video capture or microphone input. Android can only capture
eligible audio usages when an app's capture policy permits it. Some Quest
firmware or VRChat audio configurations may return silence. The APK's
capture path and panel placement still need verification on Quest hardware.

## Speaker labels and privacy

The speaker tracker uses local voice embeddings and a rolling audio window
to estimate continuity between turns. `Speaker 1` means the first tracked
voice in this session. A voice can be split across labels and similar voices
can be merged. A detected overlap is shown separately when it yields text.
VRChat supplies mixed audio, so simultaneous words and avatar identities
can be missing. By default, the companion holds a short caption history
and recent speaker embeddings in memory. Linux capture prints transcript
lines to the terminal. The app does not send captions to VRChat's chatbox.

## JSON interface

- `GET /health` checks companion availability.
- `GET /v1/latest` returns recent caption rows. LAN clients send
  `Authorization: Bearer <token>`.
- `POST /v1/audio` accepts 0.5–6 seconds of raw 16 kHz mono signed 16-bit
  little-endian PCM with `Content-Type: application/octet-stream` and the
  same bearer token. Optional headers `X-Source-Language` and
  `X-Caption-Mode` default to `auto` and `transcribe`. The result contains the
  new rows from that chunk. Linux capture mode reserves the audio source
  and returns HTTP 409 for uploads.

```json
{
  "version": 1,
  "captions": [
    {
      "id": 1,
      "speaker": 1,
      "kind": "speech",
      "language": "ja",
      "mode": "translate",
      "text": "Hello, can you hear me?",
      "timestamp": 1710000000.0
    }
  ]
}
```

`speaker` is `null` when a voice cannot be assigned. `kind` is `speech`,
`overlap`, or `unassigned`. `language` is the estimated source language, or
the language pinned in settings. `timestamp` is the host's Unix time in seconds.

## Build the APK

Install JDK 21, Android SDK Platform 36 and Build Tools 36.0.0, then run:

```sh
cd android
./gradlew assembleDebug lintDebug
```

The build produces `app/build/outputs/apk/debug/app-debug.apk`.

[Android playback capture](https://developer.android.com/media/platform/av-capture#capture_audio_playback) ·
[Meta Horizon OS app lifecycle](https://developers.meta.com/vr/documentation/unity/unity-lifecycle/) ·
[SteamVR overlays](https://github.com/ValveSoftware/openvr/wiki/IVROverlay_Overview) ·
[Speaker diarization](https://k2-fsa.github.io/sherpa/onnx/c-api/html/speaker_diarization.html)
