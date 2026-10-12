# Wi-Fi for Linux mode. Run by linux-boot.sh as root: sh wifi.sh <busybox> <chroot>. Lives on UDA so it can change without a reflash.
# The driver hard-codes /system/... paths for firmware and nvram, and wpa_supplicant needs Android's linker/libs, so Android's
# system partition (APP) is mounted read-only over /system.
B=$1; R=$2
exec > /data/local/wifi.log 2>&1
set -x
$B mount -o ro /dev/block/mmcblk0p5 /system
$B ls /system/etc | $B grep -i nvram
$B insmod /system/lib/modules/cfg80211.ko
$B insmod /system/lib/modules/bcmdhd.ko
i=0
while [ $i -lt 20 ]; do $B ifconfig wlan0 >/dev/null 2>&1 && break; $B sleep 1; i=$((i+1)); done
$B ifconfig wlan0 up
$B dmesg | $B grep -i -E 'dhd|bcm|wlan|firmware|nvram' | $B tail -12
$B mkdir -p /tmp/wpa
W=/data/misc/wifi/wpa_supplicant.conf; [ -s $W ] || W=/data/local/wifi/wpa_supplicant.conf   # Android's live list first
$B sed '/^ctrl_interface/d;/^update_config/d' $W > /tmp/wpa.conf
/system/bin/wpa_supplicant -Dnl80211 -iwlan0 -c /tmp/wpa.conf > /dev/null 2>&1 &
$B sleep 3; $B ps | $B grep wpa
$B sleep 8
# ask the router for the address we had last time (keeps PC mode pointing at the same IP) and keep renewing it
LAST=/data/local/wifi/last_ip; REQ=; [ -s $LAST ] && REQ="-r $($B cat $LAST)"
[ -d /sys/class/net/wlan0 ] && $B chroot $R /sbin/udhcpc -i wlan0 -b $REQ -p /tmp/udhcpc.pid
$B sleep 6
IP=$($B ifconfig wlan0 | $B sed -n 's/.*inet addr:\([0-9.]*\).*/\1/p'); [ -n "$IP" ] && echo $IP > $LAST
$B sleep 6
$B ifconfig wlan0
