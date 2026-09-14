#!/bin/sh
# MSU2 副屏：从仓库根目录生成源码包和单文件自解压安装包
# 用法：sh tools/package.sh [版本号]
# 测试时可用 DIST=/tmp/msu2d-dist sh tools/package.sh 1.0-test
set -eu

ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
VERSION=${1:-1.0}
DIST=${DIST:-"$ROOT/dist"}
STAGE="/tmp/msu2d-package.$$"
PKG="$STAGE/msu2d"
TARBALL="$DIST/msu2d-$VERSION.tar.gz"
INSTALLER="$DIST/msu2d-install-$VERSION.sh"

cleanup() {
	rm -rf "$STAGE"
}
trap cleanup EXIT INT TERM

for item in src docs etc luci tools AGENTS.md README.md LICENSE; do
	[ -e "$ROOT/$item" ] || { echo "缺少打包内容：$item" >&2; exit 1; }
done

mkdir -p "$PKG" "$DIST"

# 先复制到顶层目录 msu2d/，确保归档解包后与部署目录结构一致。
(
	cd "$ROOT"
	tar cf - --exclude='__pycache__' --exclude='*.pyc' \
		src docs etc luci tools AGENTS.md README.md LICENSE
) | (
	cd "$PKG"
	tar xf -
)

tar czf "$TARBALL" -C "$STAGE" msu2d

# 自解压头：只使用目标设备已有的 sh/awk/sed/tail/tar，无 base64 依赖。
HEADER="$STAGE/header.sh"
cat > "$HEADER" <<'HEADER_EOF'
#!/bin/sh
set -e
SELF="$0"
TMP="/tmp/msu2d-install.$$"
mkdir -p "$TMP"
LINE=$(awk '/^__ARCHIVE_BELOW__$/ { print NR; exit 0 }' "$SELF")
BYTES=$(sed -n "1,${LINE}p" "$SELF" | wc -c)
tail -c +$((BYTES + 1)) "$SELF" | tar xzf - -C "$TMP"
sh "$TMP/msu2d/tools/install.sh" "$@"
RET=$?
rm -rf "$TMP"
exit $RET
__ARCHIVE_BELOW__
HEADER_EOF

cat "$HEADER" "$TARBALL" > "$INSTALLER"
chmod +x "$INSTALLER"

echo "已生成："
echo "  $TARBALL"
echo "  $INSTALLER"