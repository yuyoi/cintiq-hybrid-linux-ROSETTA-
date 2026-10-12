# Rosetta Screen (Android app)

The tablet as a wireless pen display for your PC, plus the boot menu (*Wireless screen / Linux desktop / Android*).
Android 4.1+ (the Hybrid runs 4.2.1), about 25 KB, no libraries.

* `ScreenActivity` - receives AES-encrypted H.264 frames, hardware-decodes them (MediaCodec) into an overlay window
  above the system bar, and sends pen / touch / keys back as HMAC-signed UDP packets.
* `Keys` - the tablet's own keyboard for the PC (Menu key, or popped up by the PC when a text box gets the focus).
* `ChooserActivity` + `BootReceiver` - the boot menu shown at every power-on.

Config: `/sdcard/rosetta/pc.conf`, written by `pc/pair.py` (host, ports, the shared secret, optional `remote=`).

## Build

No Gradle and no Android Studio needed: `build_apk.py` uses the Android SDK build-tools + JDK that ship inside a
Unity install with Android support (or point `--unity` at yours). It compiles with `javac`, dexes with `d8`, links
with `aapt2`, aligns and signs with a local throwaway key (`debug.keystore`, made on first build, not in git).

    python android/build_apk.py [--unity "C:\Program Files\Unity\Hub\Editor\2022.3.22f1"]

Install on the tablet by opening the APK with its file manager (KingRoot kills `adb install` / `pm install`).
