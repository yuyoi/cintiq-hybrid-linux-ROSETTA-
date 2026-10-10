# Cintiq Hybrid Linux  (WIP)

<p align="center"><img src="docs/desktop.png" width="720" alt="The Rosetta-styled Linux desktop running on the Cintiq Companion Hybrid's own screen"></p>

Boot **real Linux on the Wacom Cintiq Companion Hybrid** (DTH-A1300, the Android one with the Tegra 4), on the
tablet's *own* screen, with **touch, pen, the hardware buttons, pen calibration, an on-screen keyboard and Krita**.
No bootloader unlock, no custom kernel to build, and Android stays on the tablet untouched: it boots Linux from the
*recovery* slot, and a normal power-on is still Android.

> **Made by JunkSmithWizard (JSW) together with Claude (Anthropic's AI).** Claude wrote the code and the installer.
> JSW owned the hardware, did every test on the real tablet, and made the calls that cracked it: "just modify the
> kernel", "the panel is switched, so find another way", and "stop faking it, I want it on the real screen".
> Reverse-engineered, built and tested in one long evening.

**Unofficial. Not affiliated with, or endorsed by, Wacom.** Flashing a partition can brick a device. Read
[Risks and Recovery](#risks-and-recovery) first.

## Quick start (Windows)

You need: the tablet with **root** (see [docs/ROOT.md](docs/ROOT.md)), USB debugging on, the tablet on **WiFi**,
and Python 3.8+ on the PC.

1. Download this repo (green **Code** button > *Download ZIP*) and unzip it.
2. Plug the tablet in (in Android mode) and accept the USB-debugging prompt on it.
3. Double-click **`install.bat`** and type `YES` when asked.

That's it. It backs up your original recovery, downloads what it needs, installs the desktop, flashes the Linux
image (verified byte for byte), and boots Linux. First boot returns to Android by itself after about 4 minutes so you
can never get stuck.

Linux/macOS: `./install.sh`. Want Krita too? `install.bat --krita`.

| Command | What it does |
|---|---|
| `install.bat` | Install everything and boot Linux once |
| `install.bat boot` | Boot the Linux desktop again |
| `install.bat stay` | Linux stays up until you power-cycle (no auto-return) |
| `install.bat unstay` | Back to the safe 4-minute auto-return |
| `install.bat restore` | Put your original recovery partition back |

## Screenshots

![Keyboard](docs/keyboard.png)

*The on-screen keyboard (KEYS button, or the Home button). It stays out of the way until you want it.*

![Krita](docs/krita.png)

*Krita (software canvas) running on the tablet. Slow to start, usable once loaded.*

*The look is styled after the U110 RomHex Studio / Rosetta ROM tools: dark panel, amber accents, phosphor-green terminal.*

## What works

| | |
|---|---|
| **Screen** | Linux desktop on the panel (Openbox + tint2), styled amber-on-dark |
| **Touch** | Finger tap/drag as a mouse |
| **Pen** | Hover, press and draw; a calibration tool (5-point fit) and ◀ ▲ ▼ ▶ nudge buttons |
| **Hardware buttons** | All eight Hybrid buttons, remappable from a text file |
| **Keyboard** | On-screen keyboard from the taskbar or the Home button |
| **Apps** | Terminal, file manager, text editor, htop, Krita (`--krita`) |
| **Safe** | Android untouched; power-cycle always returns to Android |

### Hardware buttons

| Button | Default action |
|---|---|
| Home (middle) | show / hide the keyboard |
| Volume + / − | undo / redo |
| Brightness − / + | brush smaller / bigger |
| Search | eraser (`E`) |
| Menu | brush (`B`) |
| Back | Escape |

Edit `/root/keymap.txt` inside Linux (the `>_` terminal button) to change any of them. It is re-read on every press.

### Pen calibration

Tap **CAL** on the taskbar: five amber crosshairs, press the pen on each. The tool fits scale, rotation and offset
and saves it; it applies instantly and across boots. The arrows next to it nudge the landing point 2 px at a time.

## How it works

The panel is **hardware-switched** between the tablet's own SoC and your PC (that's how the Hybrid works as a
Cintiq). If Android's display stops, the switch falls back to the PC input, so a plain "stop Android and draw to the
framebuffer" never reaches the panel. The recovery partition boots a stock-kernel recovery, and in that mode the
panel *does* show the framebuffer if the mode is set the way recovery sets it. So:

1. A custom ramdisk replaces the one in your **recovery** image (kernel and header stay byte-identical).
2. It starts USB-adb, mounts an Alpine Linux root filesystem from the data partition, and runs a virtual X server.
3. A tiny loop copies that X screen into the framebuffer (`FBIOPUT_VSCREENINFO` + `mmap` + `FBIOPAN_DISPLAY`).
4. A bridge reads the Wacom digitizers and buttons straight from evdev and injects them into X.

The bootloader happily boots an unsigned recovery image here, so nothing is unlocked or bypassed.

## Risks and Recovery

* The installer writes **one partition: the recovery slot (`SOS`)**, after saving your original to `backups/SOS.img`.
  Android lives on a different partition and is never written.
* A normal power-on never reads the recovery slot, so it boots Android.
* Every Linux boot clears the recovery flag first, and a watchdog reboots to Android after ~4 minutes unless you
  ran `stay`. **To leave Linux any time:** START menu > *Return to Android*, or hold power ~10 s then power on.
* **Put everything back:** `install.bat restore` writes your original recovery partition back.
* If you ever land on the Android robot with "No command": hold **Power** and tap **Volume Up** to open the recovery
  menu, then pick *reboot system now*.
* Use at your own risk. No warranty (MIT).

## Status: work in progress 🚧

* Pen works as a mouse with hover and press; **pressure and tilt are not passed to Krita yet.**
* The screen is a software copy of the X display, so expect a few frames of lag on big redraws.
* Linux is entered with `install.bat boot` (adb); making it the default power-on boot is not done and is the
  riskiest part, so it is left out.
* A *wireless Cintiq* mode (stream your PC to the tablet, pen over WiFi with real pressure) is in progress.

## Legal

Unofficial hobby project, not affiliated with Wacom. "Wacom" and "Cintiq" are trademarks of their owners, used here
only to say what the software works with. **No Wacom or NVIDIA firmware is in this repo:** the installer saves
*your own* recovery partition and builds from it, and everything else (busybox, Alpine Linux, Krita and the other
packages) is downloaded from its official source at install time under its own licence. The code in this repo is
under the MIT License ([LICENSE](LICENSE)).

Made with love for a tablet that deserved better software. Pull requests and reports from other Hybrids welcome.
