# Building the APK

I can't produce the `.apk` binary myself in this session — no internet
access here, and a first buildozer run downloads the Android SDK/NDK plus
compiles OpenCV/numpy/scikit-image for Android, which is several GB and
needs real network access. Here's the whole buildable project instead, with
two ways to actually get the APK:

## Option A — cloud build, zero local setup (recommended)

1. Create a new GitHub repo, push everything in this `lfr_app/` folder to it
   (the `.github/workflows/build.yml` is already included).
2. On GitHub: **Actions tab → "Build APK" → Run workflow**.
3. Wait ~15–25 minutes (first build is slowest; it's compiling numpy/OpenCV
   for Android from source).
4. Download the `lfr-track-analyzer-apk` artifact from the finished run —
   that's your `.apk`. Sideload it onto your phone (enable "install unknown
   apps" for whatever app you download it through).

No Android Studio, no SDK install, nothing local — GitHub's runner does it.

## Option B — build locally (Linux or WSL2 only; buildozer doesn't run on native Windows/Mac)

```bash
pip install buildozer cython
sudo apt install -y git zip unzip openjdk-17-jdk python3-pip autoconf libtool pkg-config \
    zlib1g-dev libncurses5-dev libncursesw5-dev libtinfo5 cmake libffi-dev libssl-dev

cd lfr_app
buildozer android debug
```

The APK lands in `lfr_app/bin/`. First build downloads/builds the Android
SDK+NDK automatically (can take 30–60+ min and several GB of disk).

## Project layout

```
lfr_app/
├── main.py              # Kivy UI
├── track_core.py         # same analysis pipeline as the PC script (import-only, no CLI)
├── buildozer.spec        # Android build config (permissions, deps, arch targets)
└── .github/workflows/build.yml
```

## Before you build — two things worth checking

1. **usb4a/usbserial4a driver match**: these wrap `usb-serial-for-android`,
   which auto-detects common USB-serial chips (CH340, CP2102, FTDI, PL2303).
   Check which chip is on your Arduino board (or the board's USB-serial
   adapter) — if it's an oddball, you may need to add its VID/PID to the
   library's device filter.
2. **OTG hardware**: you need an actual USB-OTG cable/adapter for the phone,
   and the phone needs to support USB host mode (most modern Android phones
   do; a few budget models don't).

## Testing the UI without building an APK

`main.py` runs on desktop too (`pip install kivy opencv-python numpy
scikit-image plyer` then `python main.py` from inside `lfr_app/`) — lets you
check the photo-pick/analyze/preview flow quickly. The "Send to Arduino"
button will just report it's Android-only when run on desktop, since
`usb4a`/`usbserial4a` don't exist outside Android.
