# 地震报告系统三端部署说明

Release 地址：

https://github.com/zhouhaoyiu/quake-report/releases/tag/oneclick-20260710

## 选择下载哪个包

| 机器 | 下载文件 | 是否需要外网 |
| --- | --- | --- |
| macOS Apple Silicon / M 系列芯片 | `quake-report-offline-macos-arm64-20260710.tar.gz` | 不需要 |
| Windows x64 | `quake-report-online-windows-x64-20260710.zip` | 首次启动及目录同步需要 |
| Linux x64 | `quake-report-online-linux-x64-20260710.tar.gz` | 首次启动及目录同步需要 |

三个包都包含当前代码、Natural Earth、国内边界、GEM 断层数据、`var/usgs_catalog.sqlite` 和 `var/usgs_catalog_m3.csv.gz`。macOS 离线包另外包含完整 Node/Python 运行环境和 LibreOffice。

## macOS Apple Silicon

适用于 M1、M2、M3、M4 等 Apple Silicon Mac。

1. 下载 `quake-report-offline-macos-arm64-20260710.tar.gz`。
2. 双击解压，或在终端运行：

   ```bash
   tar -xzf quake-report-offline-macos-arm64-20260710.tar.gz
   ```

3. 进入解压出来的文件夹。
4. 双击 `START-MAC-LINUX.command`。
5. 如果系统提示无法打开，右键点击 `START-MAC-LINUX.command`，选择“打开”。
6. 浏览器会自动打开：

   ```text
   http://localhost:3100
   ```

第一次启动会修正包内 Python 路径，可能等待 1 到 2 分钟。后续启动会更快。这个包不会访问外网；页面会显示离线 USGS 目录的截止时间。关闭启动窗口即可停止服务。

## Windows x64

适用于普通 64 位 Windows 电脑。

1. 下载 `quake-report-online-windows-x64-20260710.zip`。
2. 解压到一个英文路径目录，避免放在微信临时目录或压缩包预览窗口里直接运行。
3. 进入解压出来的文件夹。
4. 双击 `START-WINDOWS.bat`。
5. 首次启动会自动解压包内 Node.js、安装 Miniforge，并联网安装 npm/conda 依赖。
6. 浏览器会自动打开：

   ```text
   http://localhost:3100
   ```

首次启动可能需要较久，取决于网络速度。后续启动会复用 `.runtime`、`node_modules` 和 `.next`，并在启动时增量更新 USGS 目录。

## Linux x64

适用于普通 64 位 Linux 服务器或桌面。

1. 下载 `quake-report-online-linux-x64-20260710.tar.gz`。
2. 解压：

   ```bash
   tar -xzf quake-report-online-linux-x64-20260710.tar.gz
   ```

3. 进入目录：

   ```bash
   cd quake-report-online-linux-x64-20260710
   ```

4. 启动：

   ```bash
   ./START-LINUX.sh
   ```

5. 打开浏览器访问：

   ```text
   http://localhost:3100
   ```

如果是在服务器上运行，需要从本机访问服务器 IP：

```text
http://服务器IP:3100
```

首次启动会自动解压包内 Node.js、安装 Miniforge，并联网安装 npm/conda 依赖。后续启动会复用本地目录，并在启动时增量更新 USGS 目录。

Windows/Linux 的地图、Word 和目录 CSV 不依赖 LibreOffice。需要 PDF 时，请先在系统中安装 LibreOffice。

## 常见问题

### 端口 3100 被占用

换一个端口启动。

macOS / Linux：

```bash
PORT=3200 ./START-MAC-LINUX.command
```

Linux 包也可以：

```bash
PORT=3200 ./START-LINUX.sh
```

Windows PowerShell：

```powershell
$env:PORT="3200"; .\START-WINDOWS.bat
```

然后访问：

```text
http://localhost:3200
```

### Windows 提示脚本权限

右键 `START-WINDOWS.bat`，选择“以管理员身份运行”。如果仍被安全软件拦截，需要允许 PowerShell 运行本地脚本。

### Linux 不能执行脚本

运行：

```bash
chmod +x START-LINUX.sh
./START-LINUX.sh
```

### 重新部署

删除解压目录，重新解压对应压缩包即可。

### 停止服务

关闭启动窗口，或在终端按 `Ctrl+C`。
