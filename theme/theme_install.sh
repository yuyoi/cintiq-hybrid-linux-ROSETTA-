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

panel_items = PPPPPPPPPPPPTSC
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
158 Escape
EOF

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

cat > $H/krita.sh <<'EOF'
#!/bin/sh
export HOME=/root QT_QPA_PLATFORM=xcb LIBGL_ALWAYS_SOFTWARE=1 QT_QUICK_BACKEND=software
exec krita "$@"
EOF
chmod +x $H/krita.sh
mkdir -p $H/.config
printf '[]\ncanvasState=OPENGL_FAILED\nOpenGLRenderer=none\n' > $H/.config/kritarc

cat > $H/session.sh <<'EOF'
#!/bin/sh
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export HOME=/root GTK_THEME=Adwaita:dark
export DISPLAY=${DISPLAY:-:0}
xrdb -nocpp -merge /root/.Xresources
XT="-bg #0a0c0e -fg #4fd05a -cr #f0b12a +sb -fa Mono -fs 13 -bw 0 -b 12"
feh --bg-fill /root/wall.png &
openbox > /tmp/ob.log 2>&1 &
sleep 2
tint2 -c /root/.config/tint2/tint2rc > /tmp/tint2.log 2>&1 &
xterm $XT -T 'rosetta // shell' -geometry 78x26+50+60 -e /bin/sh -l &
xterm $XT -T 'monitor' -geometry 78x26+1010+110 -e htop &
pcmanfm --no-desktop > /tmp/pcmanfm.log 2>&1 &
EOF
chmod +x $H/session.sh
echo THEME-INSTALLED
