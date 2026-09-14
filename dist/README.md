# 发布包说明

本目录保存 v1.0 的发布包和完整备份，源文件仍以仓库根目录为准。源码包和单文件安装包于 2026-09-14 从整理后的仓库重新生成；`msu2d-backup-20260912.tar.gz` 保持为 2026-09-12 的历史完整备份。

| 文件 | SHA-256 |
| --- | --- |
| `msu2d-install-1.0.sh` | `836d900479ff3e7ab19c0839e42289ff14c2fde8a2bad6bf352067faeacd1856` |
| `msu2d-1.0.tar.gz` | `1e00471a34f283a3f30d0333ba8219bc1850265338adebd1d044349f67d5c96e` |
| `msu2d-backup-20260912.tar.gz` | `3e996dd304ae09c970c4f291258b68e0c1ec7a4114d059d43b06b6b35363b78c` |

## 一键安装

```sh
sh /tmp/msu2d-install-1.0.sh
```

安装脚本默认部署到 `/mnt/mmc1-4/msu2d`，失败时回退到 `/opt/msu2d`。

## 手动解包

```sh
mkdir -p /tmp/msu2d-src
tar xzf msu2d-1.0.tar.gz -C /tmp/msu2d-src
sh /tmp/msu2d-src/msu2d/tools/install.sh
```

## 完整备份还原

```sh
cd /mnt/mmc1-4
tar xzf /tmp/msu2d-backup-20260912.tar.gz
sh /mnt/mmc1-4/msu2d/tools/install.sh
```

注意：源码包和单文件安装包是 2026-09-14 构建的 v1.0 快照；仓库源码后续若有修改，应重新运行 `tools/package.sh` 打包后再分发。

## 重新生成

在仓库根目录执行 `sh tools/package.sh 1.0`。测试时可设置 `DIST=/tmp/msu2d-dist`，避免覆盖正式发布包。
