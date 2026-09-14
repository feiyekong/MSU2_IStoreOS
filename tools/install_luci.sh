#!/bin/sh
# 一键安装/更新 LuCI 模块 + 服务脚本（幂等，可重复执行）
# 用法： sh /mnt/mmc1-4/msu2d/tools/install_luci.sh
set -e
SRC=/mnt/mmc1-4/msu2d

echo "[1/4] 安装 UCI 配置"
mkdir -p /etc/config
[ -f /etc/config/msu2 ] || cp "$SRC/etc/config/msu2" /etc/config/msu2

echo "[2/4] 安装 init 服务脚本"
cp "$SRC/etc/init.d/msu2d" /etc/init.d/msu2d
chmod +x /etc/init.d/msu2d

echo "[3/4] 安装 LuCI 控制器与设置页"
mkdir -p /usr/lib/lua/luci/controller /usr/lib/lua/luci/model/cbi/msu2
cp "$SRC/luci/controller/msu2.lua" /usr/lib/lua/luci/controller/msu2.lua
cp "$SRC/luci/model/cbi/msu2/settings.lua" /usr/lib/lua/luci/model/cbi/msu2/settings.lua

echo "[4/4] 清理缓存并重启服务"
rm -rf /tmp/luci-* 2>/dev/null || true
/etc/init.d/msu2d restart >/dev/null 2>&1 || true

echo "完成。请在浏览器打开：http://192.168.10.1/cgi-bin/luci/admin/services/msu2"
echo "（菜单：服务 -> USB副屏 (MSU2)）"
