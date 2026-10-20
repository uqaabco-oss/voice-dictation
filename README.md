# voice-dictation

Local, offline push-to-talk dictation for macOS: hold Right Option, speak, release, and the cleaned-up transcript is pasted into the focused app.

It is a small, private alternative to tools like Wispr Flow for talking to an AI chat, a terminal, an editor or any other app:

- **Offline.** Whisper (`whisper-large-v3-turbo`) runs on the Mac's GPU through [MLX](https://github.com/ml-explore/mlx). Audio stays in memory and is never written to disk or sent anywhere. No account or API key is needed. The only network access is the one-time model download.
- **Light cleanup.** Filler words (um, uh, erm, and "you know" when used as filler) are removed. Spacing, capitalisation and the final punctuation are fixed. Nothing is rewritten by an LLM.
- **Pastes anywhere.** The text goes through the clipboard with Cmd+V, and your previous clipboard contents are restored afterwards.

## Requirements

- A Mac with Apple Silicon (M1 or later) on macOS 14 Sonoma or later. MLX does not support Intel Macs.
- [uv](https://docs.astral.sh/uv/) (`brew install uv`). uv installs the pinned Python 3.12 for you. The system `python3` is not used.
- About 2.5 GB of free disk space: 1.6 GB for the model and the rest for the Python packages.

## Setup

```sh
git clone https://github.com/uqaabco-oss/voice-dictation.git
cd voice-dictation
uv sync                  # installs Python 3.12 and the dependencies into .venv
uv run voice-dictation   # start it
```

On the first run it downloads the Whisper model `mlx-community/whisper-large-v3-turbo` from Hugging Face. That is **about 1.6 GB** and is saved to `~/.cache/huggingface/hub`. Later starts load the model from disk in a few seconds and make no network requests. Leave the terminal open while it runs. Press Ctrl+C to quit.

When it logs `Ready. Hold Right Option to dictate, release to paste.` you can start dictating.

## macOS permissions

macOS gives these permissions to the app that runs voice-dictation. When you start it from a terminal, that is your terminal app (Terminal, iTerm2, Ghostty, the VS Code terminal and so on), not voice-dictation itself. Inside tmux, it is the terminal app that started the tmux server.

Open **System Settings → Privacy & Security** and allow your terminal app in each of these:

| Setting | Why it is needed | How to grant it |
| --- | --- | --- |
| **Microphone** | to record while you hold the key | macOS asks the first time you dictate. To change it later: Privacy & Security → Microphone → turn your terminal on. |
| **Input Monitoring** | to notice Right Option being held anywhere | voice-dictation asks at startup. Privacy & Security → Input Monitoring → turn your terminal on (or add it with **+**). |
| **Accessibility** | to press Cmd+V for you in the focused app | voice-dictation asks at startup. Privacy & Security → Accessibility → turn your terminal on (or add it with **+**). |

After changing Input Monitoring or Accessibility, **quit the terminal app completely (Cmd+Q) and open it again**. macOS often applies these changes only to newly started apps. Then run `uv run voice-dictation` again.

If Accessibility is missing, the dictated text is still placed on the clipboard (you'll hear an error sound) so you can paste it yourself with Cmd+V.

## Using it

1. Click into the app or terminal where the text should go.
2. **Hold Right Option** and wait for the short "Tink" sound, then speak.
3. **Release Right Option.** A "Pop" sound confirms it stopped. About a second later the text is pasted.

Details:

- Taps shorter than 0.3 s are ignored, so brushing the key does nothing.
- Using Right Option together with another key or a mouse click cancels the dictation. Option shortcuts and special characters such as `Option+E` still work.
- Recordings with no speech in them (silence) are skipped. A recording that reaches 5 minutes is stopped and transcribed.
- A low "Basso" sound means something went wrong. The terminal log says what.
- Only one copy runs at a time, so you never get double pastes.

### What the cleanup does

The cleanup is deterministic and deliberately conservative. It only removes filler words and tidies punctuation, and never rewrites or reorders words.

| Spoken (Whisper output) | Pasted |
| --- | --- |
| `Um, can you, uh, refactor this function?` | `Can you refactor this function?` |
| `So, um, what do you think` | `So, what do you think.` |
| `It was, you know, really hard.` | `It was really hard.` |
| `You know what I mean?` | `You know what I mean?` (kept: not a filler here) |
| `Uh-huh, that's right` | `Uh-huh, that's right.` (kept) |

Filler removal applies to English only. For other languages, only spacing, capitalisation and punctuation are fixed.

### Options

```text
uv run voice-dictation [run] [--model MODEL] [--language LANG] [--no-sounds] [--silence-db DB] [-v]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--model` | `mlx-community/whisper-large-v3-turbo` | Any MLX Whisper repo on Hugging Face or a local folder. For example, `mlx-community/whisper-large-v3-turbo-q4` (about 0.5 GB) is smaller and uses less memory. |
| `--language` | `en` | Spoken language code (`en`, `de`, `ur`...) or `auto` to detect it. A fixed language is more reliable for short clips. |
| `--no-sounds` | off | Don't play the start, stop and error sounds. |
| `--silence-db` | `-55` | Skip recordings whose loudest moment is quieter than this many dBFS. Lower it, for example to `-70`, if quiet speech is being skipped. |
| `-v`, `--verbose` | off | Debug logging, including the raw and cleaned text. Without it, dictated text is never logged. |

## Start automatically at login (optional)

```sh
uv run voice-dictation install-launch-agent      # accepts the same options as run
uv run voice-dictation uninstall-launch-agent
```

`install-launch-agent` writes `~/Library/LaunchAgents/com.uqaabco.voice-dictation.plist` and starts the agent immediately. From then on it starts at every login, and launchd restarts it if it crashes. Its log is `~/Library/Logs/voice-dictation.log`. Any options you pass, such as `--language auto`, are saved into the agent. The agent runs from this checkout's `.venv`, so keep the folder where it is. Uninstall first if you move it.

**The agent needs its own permissions.** It runs without a terminal, so macOS asks about the Python binary it uses instead of your terminal app. The install command prints that binary's path. It looks like `~/.local/share/uv/python/cpython-3.12.*-macos-aarch64-none/bin/python3.12`. In System Settings → Privacy & Security:

- **Accessibility** and **Input Monitoring**: click **+**, press Cmd+Shift+G, paste the printed path, and add it.
- **Microphone**: macOS asks the first time you dictate. If the log keeps saying the microphone delivered only silence, the permission was denied: turn it on under Privacy & Security → Microphone.

Then restart the agent with the command the installer printed:

```sh
launchctl kickstart -k gui/$(id -u)/com.uqaabco.voice-dictation
```

To stop the agent for the current session without uninstalling it, run `launchctl bootout gui/$(id -u)/com.uqaabco.voice-dictation`. It starts again at the next login.

While the agent is running, `uv run voice-dictation` in a terminal reports that it is already running. Use one or the other.

## Troubleshooting

- **Nothing happens when holding Right Option.** Grant Input Monitoring (see above) and restart the terminal app. In Terminal and iTerm2, also make sure **Secure Keyboard Entry** (in the app menu) is off, because it hides key presses from other apps. A password field has the same effect while it is focused.
- **Text is not pasted but is on the clipboard.** Grant Accessibility and restart the terminal app.
- **"The microphone delivered only silence".** If it happens every time, Microphone access is denied for the app running voice-dictation. If it happens only now and then with Bluetooth headphones, the microphone was still starting up.
- **"Skipped ... too quiet".** The input level was below `--silence-db`. Check the input device in System Settings → Sound → Input, or lower the threshold.
- **The first word gets cut off with Bluetooth headphones.** AirPods and similar headsets take a moment to switch their microphone on. Wait a beat after the start sound, or choose the Mac's built-in microphone as the input.
- **Text with Dvorak or other non-QWERTY layouts.** The paste is sent as the key in the QWERTY "V" position with Command. If that pastes the wrong thing, use the "Dvorak - QWERTY ⌘" input source.

## Development

```sh
uv run pytest        # unit tests: no microphone, GUI or model download needed
uv run ruff check .  # lint
```

Code layout (`src/voice_dictation/`):

| Module | Responsibility |
| --- | --- |
| `cleanup.py` | Deterministic transcript cleanup (pure functions, heavily tested) |
| `controller.py` | Push-to-talk state machine and the transcribe → clean → paste pipeline |
| `hotkey.py` | Right Option detection with a listen-only Quartz event tap |
| `audio.py` | 16 kHz mono recording with `sounddevice` and a silence check |
| `transcriber.py` | `mlx-whisper` model loading (once, at startup) and transcription |
| `paste.py` | Clipboard save, paste and restore through `NSPasteboard` and Cmd+V |
| `launch_agent.py` | Login LaunchAgent plist and `launchctl` calls |
| `app.py`, `cli.py` | Startup, permission checks, the run loop and the command line |

## Possible follow-ups

These are out of scope for this version:

- A signed `.app` bundle with a menu-bar icon. It would give the permissions a stable identity instead of the terminal or Python binary.
- A settings screen, including a configurable hotkey.
- Detecting terminals, to skip the automatic trailing full stop when dictating shell commands.
- Custom vocabulary (names and jargon) through Whisper's initial prompt.
- Optional LLM polish, cloud transcription or a UI for switching languages.
