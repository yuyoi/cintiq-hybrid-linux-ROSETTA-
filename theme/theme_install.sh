#!/bin/sh
# Runs INSIDE the Alpine chroot. Installs the "Rosetta hack" desktop theme (palette from Rosetta ROM Studio).
set -e
H=/root
mkdir -p $H/.themes/RosettaHack/openbox-3 $H/.config/openbox $H/.config/tint2

cat > $H/.themes/RosettaHack/openbox-3/themerc <<'EOF'
border.width: 1
padding.width: 8
padding.height: 7
window.handle.width: 0
window.client.padding.width: 0
window.label.text.justify: left
menu.overlap: 0
menu.border.width: 1
menu.border.color: #555b61
window.active.border.color: #f0b12a
window.inactive.border.color: #2a3038
window.active.client.color: #12161a
window.inactive.client.color: #12161a
window.active.title.bg: flat solid
window.active.title.bg.color: #1d2228
window.active.title.separator.color: #f0b12a
window.inactive.title.bg: flat solid
window.inactive.title.bg.color: #12161a
window.inactive.title.separator.color: #2a3038
window.active.label.bg: parentrelative
window.inactive.label.bg: parentrelative
window.active.label.text.color: #eef1f3
window.inactive.label.text.color: #8a96a0
window.active.button.unpressed.bg: flat solid
window.active.button.unpressed.bg.color: #1d2228
window.active.button.unpressed.image.color: #f0b12a
window.active.button.hover.bg: flat solid
window.active.button.hover.bg.color: #f0b12a
window.active.button.hover.image.color: #0a0c0e
window.active.button.pressed.bg: flat solid
window.active.button.pressed.bg.color: #c8322a
window.active.button.pressed.image.color: #eef1f3
window.inactive.button.unpressed.bg: flat solid
window.inactive.button.unpressed.bg.color: #12161a
window.inactive.button.unpressed.image.color: #555b61
window.inactive.button.hover.bg: flat solid
window.inactive.button.hover.bg.color: #2a3038
window.inactive.button.hover.image.color: #eef1f3
window.inactive.button.pressed.bg: flat solid
window.inactive.button.pressed.bg.color: #c8322a
window.inactive.button.pressed.image.color: #eef1f3
window.active.button.toggled.unpressed.bg: flat solid
window.active.button.toggled.unpressed.bg.color: #1d2228
window.active.button.toggled.unpressed.image.color: #6ec8e8
window.inactive.button.toggled.unpressed.bg: flat solid
window.inactive.button.toggled.unpressed.bg.color: #12161a
window.inactive.button.toggled.unpressed.image.color: #555b61
menu.title.bg: flat solid
menu.title.bg.color: #12161a
menu.title.text.color: #f0b12a
menu.title.text.justify: left
menu.items.bg: flat solid
menu.items.bg.color: #1d2228
menu.items.text.color: #eef1f3
menu.items.disabled.text.color: #555b61
menu.items.active.bg: flat solid
menu.items.active.bg.color: #f0b12a
menu.items.active.text.color: #0a0c0e
menu.separator.color: #555b61
menu.separator.width: 1
menu.separator.padding.width: 6
menu.separator.padding.height: 3
osd.bg: flat solid
osd.bg.color: #12161a
osd.border.color: #f0b12a
osd.border.width: 1
osd.label.bg: parentrelative
osd.label.text.color: #eef1f3
osd.hilight.bg: flat solid
osd.hilight.bg.color: #f0b12a
osd.unhilight.bg: flat solid
osd.unhilight.bg.color: #1d2228
EOF

# openbox config: start from the stock one, patch theme / fonts / title layout / start-menu key
python3 - <<'EOF'
import re
s = open('/etc/xdg/openbox/rc.xml').read()
s = re.sub(r'(<theme>\s*<name>)[^<]*', r'\1RosettaHack', s, count=1)
s = re.sub(r'<titleLayout>[^<]*</titleLayout>', '<titleLayout>NLIMC</titleLayout>', s)
m = re.search(r'<theme>.*?</theme>', s, re.S)
blk = re.sub(r'<size>\d+</size>', '<size>11</size>', m.group(0))
blk = re.sub(r'<weight>[^<]*</weight>', '<weight>Bold</weight>', blk, count=2)
s = s.replace(m.group(0), blk)
key = '<keybind key="C-A-space"><action name="ShowMenu"><menu>root-menu</menu></action></keybind>\n'
s = s.replace('</keyboard>', key + '</keyboard>', 1)
rule = ('<application class="krita" name="krita"><fullscreen>no</fullscreen><maximized>no</maximized>'
        '<position force="yes"><x>20</x><y>8</y></position><size><width>1880</width><height>1000</height></size></application>\n'
        '<application class="onboard" name="onboard"><decor>no</decor><layer>above</layer><focus>no</focus></application>\n')
s = s.replace('</applications>', rule + '</applications>', 1)
open('/root/.config/openbox/rc.xml', 'w').write(s)
EOF

cat > $H/.config/openbox/menu.xml <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<openbox_menu xmlns="http://openbox.org/3.4/menu">
<menu id="root-menu" label="ROSETTA // CINTIQ">
  <item label="Terminal"><action name="Execute"><command>xterm</command></action></item>
  <item label="Krita (paint)"><action name="Execute"><command>/root/krita.sh</command></action></item>
  <item label="DOODLE DOOM (game)"><action name="Execute"><command>python3 /root/games/doodledoom.py</command></action></item>
  <item label="Straight-to-Krita on/off"><action name="Execute"><command>/root/kiosk.sh toggle</command></action></item>
  <item label="Arrange windows"><action name="Execute"><command>python3 /root/tile.py</command></action></item>
  <menu id="rotate" label="Rotate screen">
    <item label="Landscape"><action name="Execute"><command>/root/rotate.sh normal</command></action></item>
    <item label="Portrait (right)"><action name="Execute"><command>/root/rotate.sh CW</command></action></item>
    <item label="Portrait (left)"><action name="Execute"><command>/root/rotate.sh CCW</command></action></item>
    <item label="Upside down"><action name="Execute"><command>/root/rotate.sh UD</command></action></item>
  </menu>
  <item label="Files"><action name="Execute"><command>pcmanfm</command></action></item>
  <item label="Text editor"><action name="Execute"><command>mousepad</command></action></item>
  <item label="System monitor"><action name="Execute"><command>xterm -T monitor -e htop</command></action></item>
  <separator/>
  <item label="Calibrate pen"><action name="Execute"><command>/root/calib.sh pen</command></action></item>
  <item label="Calibrate touch"><action name="Execute"><command>/root/calib.sh touch</command></action></item>
  <item label="Reset calibration"><action name="Execute"><command>/root/calib.sh reset</command></action></item>
  <separator/>
  <item label="Reload desktop"><action name="Reconfigure"/></item>
  <item label="Return to Android"><action name="Execute"><command>/root/to-android.sh</command></action></item>
</menu>
</openbox_menu>
EOF

cat > $H/to-android.sh <<'EOF'
#!/bin/sh
dd if=/dev/zero of=/dev/block/platform/sdhci-tegra.3/by-name/MSC bs=2048 count=1 2>/dev/null
sync
reboot -f
EOF
chmod +x $H/to-android.sh

cat > $H/.Xresources <<'EOF'
XTerm*faceName: DejaVu Sans Mono
XTerm*faceSize: 13
XTerm*background: #0a0c0e
XTerm*foreground: #4fd05a
XTerm*cursorColor: #f0b12a
XTerm*scrollBar: false
XTerm*borderWidth: 0
XTerm*internalBorder: 12
XTerm*color0: #0a0c0e
XTerm*color1: #c8322a
XTerm*color2: #4fd05a
XTerm*color3: #f0b12a
XTerm*color4: #6ec8e8
XTerm*color5: #b08ae8
XTerm*color6: #6ec8e8
XTerm*color7: #eef1f3
XTerm*color8: #555b61
XTerm*color9: #ff5a4f
XTerm*color10: #7ae882
XTerm*color11: #ffd060
XTerm*color12: #9bdcf5
XTerm*color13: #d0b0ff
XTerm*color14: #9bdcf5
XTerm*color15: #ffffff
EOF

cat > $H/.config/tint2/tint2rc <<'EOF'
# panel bg (1), task (2), active task (3), button (4), clock (5), systray (6)
rounded = 0
border_width = 1
border_sides = T
background_color = #1d2228 100
border_color = #f0b12a 100
background_color_hover = #1d2228 100
border_color_hover = #f0b12a 100
background_color_pressed = #1d2228 100
border_color_pressed = #f0b12a 100

rounded = 0
border_width = 1
border_sides = TBLR
background_color = #12161a 100
border_color = #2a3038 100
background_color_hover = #1d2228 100
border_color_hover = #555b61 100
background_color_pressed = #1d2228 100
border_color_pressed = #555b61 100

rounded = 0
border_width = 1
border_sides = TBLR
background_color = #0a0c0e 100
border_color = #f0b12a 100
background_color_hover = #0a0c0e 100
border_color_hover = #f0b12a 100
background_color_pressed = #0a0c0e 100
border_color_pressed = #f0b12a 100

rounded = 0
border_width = 0
background_color = #f0b12a 100
border_color = #f0b12a 100
background_color_hover = #ffd060 100
border_color_hover = #ffd060 100
background_color_pressed = #c8322a 100
border_color_pressed = #c8322a 100

rounded = 0
border_width = 1
border_sides = L
background_color = #12161a 100
border_color = #2a3038 100

rounded = 0
border_width = 0
background_color = #1d2228 0
border_color = #1d2228 0

button = new
button_text = ◆ START
button_tooltip = Menu
button_lclick_command = xdotool key ctrl+alt+space
button_font = DejaVu Sans Bold 12
button_font_color = #0a0c0e 100
button_padding = 22 4
button_background_id = 4

button = new
button_text = >_
button_tooltip = Terminal
button_lclick_command = xterm
button_font = DejaVu Sans Mono Bold 12
button_font_color = #4fd05a 100
button_padding = 16 4
button_background_id = 2

button = new
button_text = FILES
button_lclick_command = pcmanfm
button_font = DejaVu Sans Bold 10
button_font_color = #6ec8e8 100
button_padding = 14 4
button_background_id = 2

button = new
button_text = ⌨ KEYS
button_tooltip = On-screen keyboard
button_lclick_command = /root/keys.sh
button_font = DejaVu Sans Bold 10
button_font_color = #eef1f3 100
button_padding = 14 4
button_background_id = 2

button = new
button_text = KRITA
button_lclick_command = /root/krita.sh
button_font = DejaVu Sans Bold 10
button_font_color = #c8322a 100
button_padding = 14 4
button_background_id = 2

button = new
button_text = MON
button_lclick_command = xterm -T monitor -e htop
button_font = DejaVu Sans Bold 10
button_font_color = #f0b12a 100
button_padding = 14 4
button_background_id = 2

button = new
button_text = PC
button_tooltip = Wireless Cintiq: show and pen-control the PC
button_lclick_command = /root/pcmode.sh
button_font = DejaVu Sans Bold 11
button_font_color = #4fd05a 100
button_padding = 16 4
button_background_id = 2

button = new
button_text = CAL
button_tooltip = Calibrate pen
button_lclick_command = /root/calib.sh pen
button_font = DejaVu Sans Bold 10
button_font_color = #f0b12a 100
button_padding = 14 4
button_background_id = 2

button = new
button_text = ◀
button_tooltip = nudge pen left
button_lclick_command = /root/nudge.sh left
button_font = DejaVu Sans Bold 12
button_font_color = #6ec8e8 100
button_padding = 14 4
button_background_id = 2

button = new
button_text = ▲
button_lclick_command = /root/nudge.sh up
button_font = DejaVu Sans Bold 12
button_font_color = #6ec8e8 100
button_padding = 14 4
button_background_id = 2

button = new
button_text = ▼
button_lclick_command = /root/nudge.sh down
button_font = DejaVu Sans Bold 12
button_font_color = #6ec8e8 100
button_padding = 14 4
button_background_id = 2

button = new
button_text = ▶
button_lclick_command = /root/nudge.sh right
button_font = DejaVu Sans Bold 12
button_font_color = #6ec8e8 100
button_padding = 14 4
button_background_id = 2

button = new
button_text = ⟲
button_tooltip = reset pen offset
button_lclick_command = /root/nudge.sh reset
button_font = DejaVu Sans Bold 12
button_font_color = #c8322a 100
button_padding = 14 4
button_background_id = 2

button = new
button_text = ROT
button_tooltip = rotate the screen (desktop restarts, open apps close)
button_lclick_command = /root/rotate.sh next
button_font = DejaVu Sans Bold 10
button_font_color = #7fd0ff 100
button_padding = 14 4
button_background_id = 2

execp = new
execp_command = /root/battery.sh
execp_tooltip = Battery and brightness (wheel = dim, click = cycle)
execp_interval = 30
execp_continuous = 0
execp_has_icon = 0
execp_mwheel_up_command = /root/bright.sh up
execp_mwheel_down_command = /root/bright.sh down
execp_lclick_command = /root/bright.sh cycle
execp_font = DejaVu Sans Bold 10
execp_font_color = #f0b12a 100
execp_padding = 14 4
execp_background_id = 2

panel_items = PPPPPPPPPPPPPPTSEC
panel_size = 100% 48
panel_margin = 0 0
panel_padding = 0 0 0
panel_background_id = 1
panel_position = bottom center horizontal
wm_menu = 0
panel_dock = 0
panel_layer = top
strut_policy = follow_size
autohide = 0

taskbar_mode = single_desktop
taskbar_padding = 6 6 6
taskbar_background_id = 0
task_text = 1
task_icon = 0
task_centered = 0
task_maximum_size = 260 48
task_padding = 14 4 4
task_background_id = 2
task_active_background_id = 3
task_urgent_background_id = 2
task_iconified_background_id = 2
task_font = DejaVu Sans Bold 10
task_font_color = #8a96a0 100
task_active_font_color = #f0b12a 100

systray_padding = 8 4 6
systray_background_id = 6
systray_sort = ascending
systray_icon_size = 28

time1_format = %H:%M
time2_format = %d %b
time1_font = DejaVu Sans Mono Bold 13
time2_font = DejaVu Sans Mono 9
clock_font_color = #eef1f3 100
clock_padding = 16 4
clock_background_id = 5

EOF

cat > $H/mkwall.py <<'EOF'
from PIL import Image, ImageDraw, ImageFont
W, H = 1920, 1080
im = Image.new('RGB', (W, H), '#0a0c0e')
d = ImageDraw.Draw(im)
for x in range(0, W, 40):
    d.line([(x, 0), (x, H)], fill='#11161b' if x % 200 else '#1a2128')
for y in range(0, H, 40):
    d.line([(0, y), (W, y)], fill='#11161b' if y % 200 else '#1a2128')
def font(sz, bold=False):
    for p in ('/usr/share/fonts/dejavu/DejaVuSansMono-Bold.ttf' if bold else '/usr/share/fonts/dejavu/DejaVuSansMono.ttf',
              '/usr/share/fonts/TTF/DejaVuSansMono.ttf'):
        try: return ImageFont.truetype(p, sz)
        except Exception: pass
    return ImageFont.load_default()
A = '#f0b12a'
for (x, y, sx, sy) in ((30, 30, 1, 1), (W - 30, 30, -1, 1), (30, H - 90, 1, -1), (W - 30, H - 90, -1, -1)):
    d.line([(x, y), (x + 70 * sx, y)], fill=A, width=3)
    d.line([(x, y), (x, y + 70 * sy)], fill=A, width=3)
d.text((W - 90, H - 230), 'ROSETTA', font=font(110, True), fill='#1d2228', anchor='rs')
d.text((W - 96, H - 190), 'CINTIQ // TEGRA4 // LINUX 3.4', font=font(26), fill='#6ec8e8', anchor='rs')
d.text((96, 90), '> boot: recovery slot  ok', font=font(22), fill='#4fd05a')
d.text((96, 122), '> android: parked', font=font(22), fill='#555b61')
d.text((96, 154), '> panel: online', font=font(22), fill='#f0b12a')
im.save('/root/wall.png')
EOF
python3 $H/mkwall.py

cat > $H/keymap.txt <<'EOF'
# hardware button map: <linux key code> <action>   (re-read on every press, edit freely)
# actions: toggle_kbd, or any xdotool key name such as ctrl+z, e, b, less, greater
# seen on this tablet: 102 home, 139 menu, 114 vol-, 115 vol+, 194 F20, 217 search, 224 bright-, 225 bright+
102 toggle_kbd
194 toggle_kbd
115 ctrl+z
114 ctrl+shift+z
224 less
225 greater
217 e
139 b
158 pc_toggle
EOF

cat > $H/pcmode.sh <<'EOF'
#!/bin/sh
# Toggle PC mode: the PC's screen fills the panel (video straight into the framebuffer), the pen goes to the PC.
# Config in /root/pc.conf:  host=<pc ip>  port=5600  secret=<hex>  video_port=5700
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin DISPLAY=${DISPLAY:-:0}
[ -f /root/pc.conf ] && . /root/pc.conf
if [ -f /tmp/pcmode ]; then
  rm -f /tmp/pcmode
  pkill -f 'ffmpeg.*fbdev' 2>/dev/null
  rm -f /tmp/mirror.pause
  [ -f /tmp/native-x ] && xinput enable pen
else
  [ -f /root/pc.conf ] || { echo "no /root/pc.conf" > /tmp/pcmode.err; exit 1; }
  touch /tmp/pcmode /tmp/mirror.pause
  echo 4194304 > /proc/sys/net/core/rmem_max 2>/dev/null     # let the video socket buffer Wi-Fi bursts
  [ -f /tmp/native-x ] && xinput disable pen          # native X: the pen must only draw on the PC, not the hidden desktop
  # the video has to match the framebuffer's byte order (native X uses RGBA, the Xvfb mirror BGRA)
  FMT=$(python3 -c "import fcntl,struct;b=bytearray(160);fcntl.ioctl(open('/dev/graphics/fb0','rb'),0x4600,b);print('rgba' if struct.unpack('<40I',bytes(b))[8]==0 else 'bgra')")
  ffmpeg -hide_banner -loglevel warning -fflags nobuffer -flags low_delay -probesize 64k -analyzeduration 0 \
    -threads 4 -thread_type slice -thread_queue_size 2 -i "udp://0.0.0.0:${video_port:-5700}?fifo_size=20000&overrun_nonfatal=1&buffer_size=4194304" -an -filter_threads 4 \
    -vf "scale=1920:1080:flags=fast_bilinear,format=${FMT:-rgba}" -fps_mode passthrough -f fbdev /dev/graphics/fb0 >/tmp/pcvideo.log 2>&1 &
  # rescue: if the video player died, go straight back to the desktop instead of leaving the screen frozen
  ( sleep 4; pgrep -f 'ffmpeg.*fbdev' >/dev/null || { rm -f /tmp/pcmode /tmp/mirror.pause; [ -f /tmp/native-x ] && xinput enable pen; echo "video failed: see /tmp/pcvideo.log" > /tmp/pcmode.err; } ) &
fi
EOF
chmod +x $H/pcmode.sh
[ -f $H/pc.conf ] || printf '# written by the PC side; see pc_remote/\nhost=CHANGE_ME\nport=5600\nsecret=CHANGE_ME\nvideo_port=5700\n' > $H/pc.conf

cat > $H/calib.sh <<'EOF'
#!/bin/sh
# usage: calib.sh pen|touch|reset
case $1 in
  reset) rm -f /root/calib_pen.json /root/calib_touch.json; echo "0 0" > /root/offset_pen.txt; echo "0 0" > /root/offset_touch.txt ;;
  *) touch /root/calib_start_${1:-pen} ;;
esac
EOF
chmod +x $H/calib.sh

cat > $H/nudge.sh <<'EOF'
#!/bin/sh
# usage: nudge.sh left|right|up|down|reset [pen|touch] [step]
K=${2:-pen}; S=${3:-2}; F=/root/offset_$K.txt
[ -f $F ] || echo "0 0" > $F
read dx dy < $F
case $1 in left) dx=$((dx-S));; right) dx=$((dx+S));; up) dy=$((dy-S));; down) dy=$((dy+S));; reset) dx=0; dy=0;; esac
echo "$dx $dy" > $F
EOF
chmod +x $H/nudge.sh
[ -f $H/offset_pen.txt ] || echo "0 0" > $H/offset_pen.txt
[ -f $H/offset_touch.txt ] || echo "0 0" > $H/offset_touch.txt

cat > $H/battery.sh <<'EOF'
#!/bin/sh
# One short line for the taskbar: "AC 95%" / "BAT 72%" / "BAT 12% LOW"
P=/sys/class/power_supply
C=$(cat $P/battery/capacity 2>/dev/null)
S=$(cat $P/battery/status 2>/dev/null)
A=$(cat $P/ac/online 2>/dev/null)
case $C in ''|*[!0-9]*) C=? ;; esac
if [ "$A" = "1" ] || [ "$S" = "Charging" ] || [ "$S" = "Full" ]; then
  echo "AC ${C}%"
elif [ "$C" != "?" ] && [ "$C" -lt 15 ]; then
  echo "BAT ${C}% LOW"
else
  echo "BAT ${C}%"
fi
EOF
chmod +x $H/battery.sh

cat > $H/bright.sh <<'EOF'
#!/bin/sh
# usage: bright.sh up|down|cycle
# step 25, clamped to 10..255; cycle goes 255 -> 128 -> 40 -> 255
B=/sys/class/backlight/pwm-backlight/brightness
S=/root/brightness.txt
# the saved value wins over the live one, so idledim.py dimming (20) is ignored here
cur=$(cat $S 2>/dev/null)
[ -f $S ] || cur=$(cat $B 2>/dev/null)
case $cur in ''|*[!0-9]*) cur=255 ;; esac
case $1 in
  up) n=$((cur+25)); [ $n -gt 255 ] && n=255 ;;
  down) n=$((cur-25)); [ $n -lt 10 ] && n=10 ;;
  cycle) if [ $cur -ge 240 ]; then n=128; elif [ $cur -ge 110 ]; then n=40; else n=255; fi ;;
  *) n=$cur ;;
esac
[ $n -lt 10 ] && n=10
[ $n -gt 255 ] && n=255
echo $n > $B 2>/dev/null
echo $n > $S
EOF
chmod +x $H/bright.sh

cat > $H/kiosk.sh <<'EOF'
#!/bin/sh
# usage: kiosk.sh toggle|status
# "Straight-to-Krita" mode: session.sh then boots wallpaper + openbox + tint2 + Krita only.
F=/root/kiosk_krita
case $1 in
  toggle)
    if [ -f $F ]; then rm -f $F; echo "Straight-to-Krita: off"
    else touch $F; echo "Straight-to-Krita: on"; fi ;;
  status) [ -f $F ] && echo "Straight-to-Krita: on" || echo "Straight-to-Krita: off" ;;
  *) echo "usage: kiosk.sh toggle|status"; exit 1 ;;
esac
EOF
chmod +x $H/kiosk.sh

cat > $H/keys.sh <<'EOF'
#!/bin/sh
export HOME=/root GSETTINGS_BACKEND=memory NO_AT_BRIDGE=1 DISPLAY=${DISPLAY:-:0}
if pgrep -f 'svkbd-mobile-intl' >/dev/null 2>&1; then
  pkill -f 'svkbd-mobile-intl'
else
  svkbd-mobile-intl -d -g 1840x470+40+560 >/tmp/svkbd.log 2>&1 &
fi
EOF
chmod +x $H/keys.sh

cat > $H/rotate.sh <<'EOF'
#!/bin/sh
# usage: rotate.sh next|normal|CW|UD|CCW - X can only rotate at start-up, so the desktop restarts (open apps close)
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
[ -f /tmp/native-x ] || { echo "rotation needs native X" > /tmp/rotate.err; exit 1; }
cur=$(cat /root/rotation 2>/dev/null); [ -n "$cur" ] || cur=normal
case "$1" in
  normal|CW|UD|CCW) new=$1 ;;
  *) case "$cur" in normal) new=CW ;; CW) new=UD ;; UD) new=CCW ;; *) new=normal ;; esac ;;
esac
[ "$new" = "$cur" ] && exit 0
echo $new > /root/rotation
setsid sh /root/restart-desktop.sh > /tmp/restart-desktop.out 2>&1 < /dev/null &
EOF
chmod +x $H/rotate.sh

cat > $H/restart-desktop.sh <<'EOF'
#!/bin/sh
# Stop X and its helpers, then run the normal start-up again (go.sh picks native X, rotation, fallback)
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
pkill -f 'sh /tmp/go.sh'
pkill -f '^python3 /tmp/touch.py'; pkill -f '^python3 /tmp/fbpush.py'; pkill -f '^python3 /root/idledim.py'
pkill -f '^python3 /tmp/mirror.py'; pkill -x Xvfb; pkill -f '^/usr/libexec/Xorg'
# wait until the old X server is really gone (its socket must be free before the new one starts)
i=0; while [ $i -lt 40 ] && { pgrep -f '^/usr/libexec/Xorg' > /dev/null || pgrep -x Xvfb > /dev/null; }; do sleep 0.25; i=$((i+1)); done
pkill -9 -f '^/usr/libexec/Xorg'; pkill -9 -x Xvfb; sleep 0.5
rm -f /tmp/.X0-lock /tmp/.X11-unix/X0
setsid sh /tmp/go.sh > /tmp/go.out 2>&1 < /dev/null &
EOF
chmod +x $H/restart-desktop.sh

cat > $H/krita.sh <<'EOF'
#!/bin/sh
# already running: bring it to the front instead of starting a second copy (two copies lock the resource database)
if pgrep -x krita >/dev/null; then
  w=$(DISPLAY=${DISPLAY:-:0} xdotool search --onlyvisible --class krita | tail -n 1)
  [ -n "$w" ] && DISPLAY=${DISPLAY:-:0} xdotool windowactivate "$w"
  exit 0
fi
# Krita must not use OpenGL: with llvmpipe its window only paints the top part
export HOME=/root QT_QPA_PLATFORM=xcb LIBGL_ALWAYS_SOFTWARE=1 QT_QUICK_BACKEND=software QT_XCB_GL_INTEGRATION=none
sed -i 's/^canvasState=.*/canvasState=OPENGL_FAILED/; s/^OpenGLRenderer=.*/OpenGLRenderer=none/' /root/.config/kritarc 2>/dev/null
# Krita's first-run copy of its default brushes/patterns into the user folder can fail ("no brush presets"); fill any gaps
S=/usr/share/krita; U=/root/.local/share/krita
for d in brushes paintoppresets patterns gradients palettes workspaces seexpr_scripts gamutmasks windowlayouts; do
  [ -d $S/$d ] || continue; mkdir -p $U/$d
  for f in "$S/$d"/*; do [ -e "$U/$d/${f##*/}" ] || cp -r "$f" "$U/$d/"; done
done
exec krita "$@"
EOF
chmod +x $H/krita.sh
mkdir -p $H/.config
[ -f $H/.config/kritarc ] || printf '[]\ncanvasState=OPENGL_FAILED\nOpenGLRenderer=none\n' > $H/.config/kritarc   # never overwrite the user's Krita settings

cat > $H/idledim.py <<'EOF'
#!/usr/bin/env python3
# Dim the panel after 5 idle minutes, put it straight back on touch/pen/key.
# Never while /tmp/pcmode exists: the panel shows the PC video and X sees no input.
import os, time, traceback
from Xlib import display
from Xlib.ext import screensaver

BRI = '/sys/class/backlight/pwm-backlight/brightness'
DIM = 20
IDLE_MS = 300000
WOKE_MS = 2000
LOG = '/tmp/idledim.log'


def log(msg):
    try:
        with open(LOG, 'a') as f:
            f.write(time.strftime('%H:%M:%S ') + msg + '\n')
    except Exception:
        pass


def read_bri():
    try:
        with open(BRI) as f:
            return int(f.read().strip())
    except Exception:
        return None


def write_bri(v):
    try:
        with open(BRI, 'w') as f:
            f.write(str(int(v)))
    except Exception:
        pass


def main():
    dpy = None
    root = None
    saved = None
    while True:
        try:
            if dpy is None:
                dpy = display.Display()
                root = dpy.screen().root
            ms = root.screensaver_query_info().idle
            pc = os.path.exists('/tmp/pcmode')
            if saved is not None:
                if ms < WOKE_MS or pc:
                    write_bri(saved)
                    log('brightness back to %d' % saved)
                    saved = None
                    continue
                time.sleep(0.3)
                continue
            if not pc and ms > IDLE_MS:
                cur = read_bri()
                if cur is not None and cur > DIM:
                    saved = cur
                    write_bri(DIM)
                    log('idle %d s: dim to %d' % (ms // 1000, DIM))
            time.sleep(2)
        except Exception:
            # never leave the screen stuck dimmed because of a hiccup
            log(traceback.format_exc().splitlines()[-1])
            if saved is not None:
                write_bri(saved)
                saved = None
            dpy = None
            time.sleep(3)


main()
EOF

cat > $H/tile.py <<'EOF'
# Arrange the open windows to fit the screen: side by side in landscape, stacked in portrait.
# Uses the work area openbox publishes (screen minus the taskbar) and its client list.
import subprocess, sys
from Xlib import X, display
d = display.Display(); root = d.screen().root
A = lambda n: d.intern_atom(n)
def prop(w, name):
    p = w.get_full_property(A(name), X.AnyPropertyType)
    return list(p.value) if p else []
wa = prop(root, '_NET_WORKAREA')[:4] or [0, 0, root.get_geometry().width, root.get_geometry().height]
x0, y0, ww, wh = wa
skip = {A('_NET_WM_WINDOW_TYPE_DOCK'), A('_NET_WM_WINDOW_TYPE_DESKTOP'), A('_NET_WM_WINDOW_TYPE_SPLASH')}
wins = []
for wid in prop(root, '_NET_CLIENT_LIST'):
    w = d.create_resource_object('window', wid)
    try:
        if skip & set(prop(w, '_NET_WM_WINDOW_TYPE')): continue
        if A('_NET_WM_STATE_HIDDEN') in prop(w, '_NET_WM_STATE'): continue
        wins.append(wid)
    except Exception:
        pass
n = len(wins)
if not n: sys.exit(0)
portrait = wh > ww
cols = 1 if portrait else min(n, 2)
rows = (n + cols - 1) // cols
gap, deco = 8, 30                    # gap between windows, openbox title bar height
cw, ch = (ww - gap * (cols + 1)) // cols, (wh - gap * (rows + 1)) // rows
for i, wid in enumerate(wins):
    c, r = i % cols, i // cols
    x, y = x0 + gap + c * (cw + gap), y0 + gap + r * (ch + gap)
    subprocess.call(['xdotool', 'windowsize', str(wid), str(cw), str(ch - deco)])
    subprocess.call(['xdotool', 'windowmove', str(wid), str(x), str(y)])
EOF

cat > $H/session.sh <<'EOF'
#!/bin/sh
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export HOME=/root GTK_THEME=Adwaita:dark
export DISPLAY=${DISPLAY:-:0}
# put the panel back at the brightness the user last chose (bright.sh keeps it)
if [ -f /root/brightness.txt ]; then
  cat /root/brightness.txt > /sys/class/backlight/pwm-backlight/brightness 2>/dev/null
fi
python3 /root/idledim.py > /dev/null 2>&1 &
xrdb -nocpp -merge /root/.Xresources
XT="-bg #0a0c0e -fg #4fd05a -cr #f0b12a +sb -fa Mono -fs 13 -bw 0 -b 12"
feh --bg-fill /root/wall.png &
openbox > /tmp/ob.log 2>&1 &
sleep 2
tint2 -c /root/.config/tint2/tint2rc > /tmp/tint2.log 2>&1 &
if [ -f /root/kiosk_krita ]; then
  /root/krita.sh &
else
  xterm $XT -T 'rosetta // shell' -geometry 78x26+50+60 -e /bin/sh -l &
  xterm $XT -T 'monitor' -geometry 78x26+1010+110 -e htop &
  pcmanfm --no-desktop > /tmp/pcmanfm.log 2>&1 &
  ( sleep 4; python3 /root/tile.py > /tmp/tile.log 2>&1 ) &     # fit the windows to this orientation
fi
EOF
chmod +x $H/session.sh
echo THEME-INSTALLED
