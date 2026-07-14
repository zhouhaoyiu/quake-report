# Windows / Linux 联网包使用说明

适用文件：

- Windows x64：`quake-report-online-windows-x64-20260715.zip`
- Linux x64：`quake-report-online-linux-x64-20260715.tar.gz`

两个包分别对应 64 位 Windows 和 x86_64 Linux，运行环境不能跨平台混用。

## 使用前准备

- 第一次启动必须能够访问 npm、conda-forge 和 USGS。
- 建议至少预留 5 GB 可用空间。
- 解压目录必须可写。Windows 建议使用短英文路径，例如 `D:\quake-report`。
- 不要在微信临时目录、压缩包预览窗口或只读目录中直接运行。
- 杀毒软件或单位网络代理可能拦截安装和下载，需要按本单位规则放行。

## 包内包含什么

- 当前版本的地震报告网页系统和项目代码
- 对应平台的 Node.js 与 Miniforge 安装器
- Natural Earth、国内边界和 GEM 断层数据
- 一份可直接使用的 USGS M3.0 及以上本地目录

Node.js 安装器和 Miniforge 安装器已经放在压缩包的 `.installers` 目录中，不需要另外下载。npm 模块和 Python 科学计算依赖会在第一次启动时联网安装。

## Windows x64

适用于普通 64 位 Windows 10 或 Windows 11 电脑。

1. 完整解压 `quake-report-online-windows-x64-20260715.zip`。
2. 进入解压后的 `quake-report-online-windows-x64-20260715` 文件夹。
3. 双击 `START-WINDOWS.bat`。
4. 保持命令窗口开启，等待首次安装完成。
5. 浏览器会自动打开：

   ```text
   http://localhost:3100
   ```

首次运行会在当前目录创建 `.runtime`，安装 Python 3.11、Cartopy 等依赖，并构建网页服务。耗时取决于网络速度；安装过程中不要关闭窗口。

通常不需要管理员权限。如果 Windows SmartScreen 拦截脚本，请确认文件来自本交付包，再选择“更多信息”并允许运行。

## Linux x64

适用于 x86_64 Linux，需要系统已有 `bash`、`tar`、`find` 等基础工具。

1. 解压并进入目录：

   ```bash
   tar -xzf quake-report-online-linux-x64-20260715.tar.gz
   cd quake-report-online-linux-x64-20260715
   ```

2. 启动：

   ```bash
   chmod +x START-LINUX.sh
   ./START-LINUX.sh
   ```

3. 桌面环境会尝试自动打开浏览器，也可以手动访问：

   ```text
   http://localhost:3100
   ```

首次运行会把 Node.js 和 Miniforge 安装到当前目录的 `.runtime`，随后安装依赖并构建网页服务，不会修改系统 Python 环境。

### 在 Linux 服务器上供其他电脑访问

默认只监听本机。需要通过服务器 IP 访问时运行：

```bash
HOSTNAME=0.0.0.0 PORT=3100 ./START-LINUX.sh
```

然后在其他电脑打开 `http://服务器IP:3100`。服务器防火墙和安全组也必须允许该端口；不要把未做访问控制的服务直接暴露到公网。

## 后续每次运行

Windows 再次双击 `START-WINDOWS.bat`，Linux 再次运行 `./START-LINUX.sh`。

启动脚本会复用 `.runtime`、`node_modules` 和 `.next`，不会重复安装完整环境。每次启动会先增量更新 USGS 目录；更新失败时会显示警告，并继续使用包内已有目录启动。

第一次安装成功后，短时断网通常仍可运行已有环境。断网期间 USGS 目录不能更新，Event ID 和近期事件只能查到本地目录截止时间以内的数据。

## 输出文件

- 地图 PNG：直接生成
- 地震目录 CSV：直接生成
- Word DOCX：直接生成
- PDF：需要操作系统已安装 LibreOffice

未安装 LibreOffice 不影响地图、CSV 和 Word。需要 PDF 时，可以安装 LibreOffice 后重新启动服务，也可以下载 Word 后在其他电脑转换。

如果 Windows 已安装 LibreOffice，但页面仍提示找不到 `soffice`，请在 PowerShell 中运行：

```powershell
$env:LIBREOFFICE_BIN="C:\Program Files\LibreOffice\program\soffice.exe"
.\START-WINDOWS.bat
```

Linux 通过系统软件源安装 LibreOffice 后，确认终端可以运行 `libreoffice --version`，再重新启动本系统。

## 停止服务

关闭启动窗口，或在终端按 `Ctrl+C`。下次使用时重新运行启动脚本即可。

## 常见问题

### 浏览器没有自动打开

确认启动窗口仍在运行，然后手动访问 `http://localhost:3100`。

### 端口 3100 已被占用

Windows PowerShell：

```powershell
$env:PORT="3200"; .\START-WINDOWS.bat
```

Linux：

```bash
PORT=3200 ./START-LINUX.sh
```

随后访问 `http://localhost:3200`。

### npm 或 conda 下载失败

检查外网、代理、防火墙和磁盘空间。网络恢复后重新运行启动脚本；已经下载完成的内容会尽量复用。

### Linux 提示 Permission denied

运行：

```bash
chmod +x START-LINUX.sh
./START-LINUX.sh
```

### Windows 找不到文件或安装失败

确认已经完整解压，并把目录移动到短英文路径。不要只复制 `START-WINDOWS.bat`，也不要删除隐藏的 `.installers` 目录。

### 需要重新部署

关闭服务后，重新解压一份完整压缩包。保留旧目录作为临时备份，确认新版可用后再删除旧目录。
