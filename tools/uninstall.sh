#!/bin/sh
# MSU2 副屏 —— 卸载脚本
# 用法： sh uninstall.sh [安装目录]   默认 /mnt/mmc1-4/msu2d
DEST=${1:-/mnt/mmc1-4/msu2d}
echo "=== 卸载 MSU2 副屏 ==="
/etc/init.d/msu2d stop 2>/dev/null || true
/etc/init.d/msu2d disable 2>/dev/null || true
rm -f /etc/init.d/msu2d
rm -f /usr/lib/lua/luci/controller/msu2.lua
rm -rf /usr/lib/lua/luci/model/cbi/msu2
rm -rf /tmp/luci-* 2>/dev/null || true
echo "已移除服务与 LuCI 页面"
echo "配置 /etc/config/msu2 与程序目录 $DEST 保留未删（如需彻底删除请手动 rm）"
echo "彻底删除： rm -rf $DEST /etc/config/msu2"
