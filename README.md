# WiVRn Translations

WiVRn Translations transcribes incoming VRChat audio. The Linux companion runs multilingual
speech recognition and optional speaker diarization locally. Its browser monitor
and Android/Quest panel group captions into separate, color-coded speaker rows.
The transparent WayVR overlay for WiVRn shows English translations of Portuguese speech for up to three speakers.

## Linux · capture VRChat playback

Start VRChat and let it play audio. On the Linux host, install Python 3.12 and the
PulseAudio client utilities (`pactl` and `parec`). The same commands work with
PipeWire-Pulse if your session exposes the VRChat playback stream.

```sh
git clone https://github.com/judge2020/wivrn-translations.git
cd wivrn-translations
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r requirements-speakers.txt
mkdir -p models
curl -fL https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2 |
  tar -xj -C models
curl -fL https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx   -o models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx
```

The first run downloads a multilingual Whisper model. Browse to
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
`"mode": "transcribe"` to preserve the spoken language. Outside the Linux WayVR mode, captions arrive in
batches of up to six seconds, plus inference time. Smaller chunks trade
speaker and speech accuracy for responsiveness. If processing falls behind,
live capture prioritizes the newest audio.

## Display in VR

### WiVRn / WayVR

Start WayVR through WiVRn and keep it running while playing VRChat. Install
the system GTK 4 and Python GObject packages (`gtk4` and `python3-gobject` on
Fedora, or `gir1.2-gtk-4.0` and `python3-gi` on Debian/Ubuntu). The companion
uses `wayvrctl` to open a transparent caption window inside WayVR's OpenXR
overlay. The spaces between speaker captions are fully transparent and an
idle window draws nothing. Install `iso-codes` for full language names.

```sh
python -m companion --vrchat --speakers models --wayvr
```

If the working set is hidden, open it with the WayVR toggle and select
**WiVRn Translations** from its taskbar. Use WayVR's **Edit mode** to
position the window and enable **Always visible** if you want captions to
stay up while the working set is hidden. Press Ctrl+C in the companion
terminal to stop capture and close the window. The Linux overlay works
with the WiVRn headset stream and requires no headset APK. When `--wayvr`
is active, the companion detects the source language for each speech turn
and translates confident Portuguese detections into English. Each speaker
row is labeled **Portuguese**. Short or ambiguous clips may wait for more
context. The overlay applies this automatically, regardless of the
`language` and `mode` settings.

WayVR uses the multilingual Whisper `small` model by default for Portuguese
recognition. Set `"model": "base"` in the JSON config if you prefer quicker
updates at the cost of some recognition accuracy. Other companion modes
still default to `base`.

For Linux playback, WayVR refreshes each speaker's translation from a
rolling audio window about every 0.8 seconds, plus inference time. New
words appear as the speaker talks and the dimmer draft words can change
as more context arrives. When the diarizer detects an overlap, the
companion uses Conv-TasNet to split the mix into up to two voice tracks
and translates them independently. Voice tracks are matched to recent
speaker labels by voice similarity. Overlapping audio is an estimate;
background noise, similar voices, and three or more simultaneous speakers
can reduce accuracy.

With `--speakers models`, the first WayVR run fetches the [ONNX
separator](https://huggingface.co/iamdgarcia/ConvTasNet_Libri2Mix_sepnoisy_16k-onnx).
For offline startup you can place `convtasnet_sepnoisy_16k.onnx` directly
in the speaker model directory. The published model is CC BY-SA 4.0 and
trained primarily on English mixtures. Separation of other languages works
by voice acoustics and accuracy varies by recording.

[WayVR setup and controls](https://github.com/wayvr-org/wayvr#first-start)

### SteamVR

With SteamVR running, add `--steamvr` to the Linux command:

```sh
pip install -r requirements-steamvr.txt
python -m companion --vrchat --speakers models --steamvr
```

VRChat must be visible through the SteamVR compositor for the head-locked
panel to appear. For CJK caption glyphs, install your distro's Noto Sans CJK
fonts.

### Android / Quest Pro panel

1. Download the APK from [Releases](https://github.com/judge2020/wivrn-translations/releases).
   Sideload it in developer mode with `adb install wivrn-translations-0.1.2.apk` and
   launch **WiVRn Translations** from Unknown Sources. The app uses standard Android
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
display. The app requests an audio-only stream limited to VRChat's app
UID, with no video capture or microphone input. Android can only capture
eligible audio usages when an app's capture policy permits it. Some Quest
firmware or VRChat audio configurations may return silence. The APK's
capture path and panel placement still need verification on Quest hardware.

## Speaker labels and privacy

The speaker tracker uses local voice embeddings and a rolling audio window
to estimate continuity between turns. `Speaker 1` means the first tracked
voice in this session. A voice can be split across labels and similar voices
can be merged. If overlap cannot be assigned to individual voices, it is labeled as overlapping speech.
VRChat supplies mixed audio, so simultaneous words and avatar identities
can be missing. By default, the companion holds a short caption history
and recent speaker embeddings in memory. Linux capture prints transcript
lines to the terminal unless the WayVR overlay is active. The app does not send captions to VRChat's chatbox.

## Lumince Singularity app catalog

[db.json](db.json) follows the [Singularity Apps catalog schema](https://github.com/Lumince/Singularity-Apps-repo).
The entry targets Quest Pro and resolves the APK from this repository's latest
GitHub release. It can be included in a Singularity-style catalog. The Lumince
app's standard Apps list loads the upstream catalog, so adding a file here
does not put the app into that list. The release APK can be sideloaded directly.

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
For progressive WayVR rows, `stable_words` counts the leading words that
matched the previous update. The remaining words are provisional.

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
