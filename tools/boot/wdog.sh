#!/sbin/busybox sh
# Independent watchdog: always return to Android after 150 s unless /data/local/linux-stay.flag exists.
B=/sbin/busybox
MISC=/dev/block/platform/sdhci-tegra.3/by-name/MSC
$B sleep 230
$B mkdir -p /data
$B mountpoint -q /data || $B mount -t ext4 /dev/block/platform/sdhci-tegra.3/by-name/UDA /data
if [ -f /data/local/linux-stay.flag ]; then exit 0; fi
$B cp /tmp/lb.log /data/local/linux-boot.log 2>/dev/null
$B dd if=/dev/zero of=$MISC bs=2048 count=1
$B sync
$B reboot -f
