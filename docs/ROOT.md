# Rooting the Cintiq Companion Hybrid

The installer needs `su` (root). The Hybrid ships Android 4.2.1 (build `CINTIQ-CH_V1.04.006`, Jan 2014) with kernel
3.4.10, which predates the 2014 kernel fixes, so it can be rooted with a one-tap kernel-exploit root app.

What worked on the unit this was built on:

1. Switch the tablet to Android mode (unplug HDMI/USB from the PC) and enable *Settings > Developer options > USB debugging*.
2. Run a Towelroot-style one-tap root app and tap "make it ra1n".
3. Install SuperSU so there is a normal `su` binary and a grant prompt. Check it from the PC:

       adb shell su -c id        ->  uid=0(root) ...

If `su` prints `uid=0`, you are done and can run `install.bat`. This repo does not include any root tool; get them
from their own authors, and only root a device you own.
