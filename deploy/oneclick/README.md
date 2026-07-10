# macOS 离线包使用说明

适用文件：`quake-report-offline-macos-arm64-20260710.tar.gz`

这个包只适用于 Apple Silicon Mac，也就是 M1、M2、M3、M4 等 M 系列芯片。Intel Mac、Windows 和 Linux 不能使用包内运行环境。

## 使用前准备

- 全程可以断网运行。
- 建议至少预留 4 GB 可用空间。
- 先把压缩包复制到 Mac 本地磁盘，再解压运行。不要直接在移动硬盘或压缩包预览窗口中启动。
- 解压后不要移动、改名或删除包内的 `.runtime`、`.next`、`data`、`scripts`、`var` 等目录。

## 包内包含什么

- 当前版本的地震报告网页系统和项目代码
- Node.js 与 Python 3.11 运行环境
- NumPy、Pandas、Matplotlib、Cartopy 等 Python 依赖
- Natural Earth、国内边界和 GEM 断层数据
- USGS M3.0 及以上本地地震目录
- LibreOffice，用于离线生成 PDF

接收方不需要安装 Node.js、Python、Conda、Cartopy 或 LibreOffice。

## 第一次启动

1. 双击压缩包解压，或在终端运行：

   ```bash
   tar -xzf quake-report-offline-macos-arm64-20260710.tar.gz
   ```

2. 打开解压后的 `quake-report-offline-macos-arm64-20260710` 文件夹。
3. 双击 `START-MAC-LINUX.command`。
4. 如果 macOS 提示无法验证开发者，右键点击该文件，选择“打开”，再确认一次。
5. 等待浏览器自动打开：

   ```text
   http://localhost:3100
   ```

第一次启动会修正包内 Python 路径并建立字体缓存，通常需要 1 到 2 分钟。看到网页后即可生成地图、目录 CSV、Word 和 PDF。

如果双击仍不能运行，在解压目录打开终端后执行：

```bash
chmod +x START-MAC-LINUX.command
xattr -dr com.apple.quarantine .
./START-MAC-LINUX.command
```

## 后续每次运行

进入同一个解压目录，再双击 `START-MAC-LINUX.command`。已经建立的运行环境和缓存会继续使用，通常比第一次快。

不要每次重新解压，也不要删除 `.runtime` 或 `.cache`。

## 离线数据范围

页面右上角会显示包内 USGS 目录的截止时间。以下功能都读取本地目录：

- Event ID 查询
- 近期地震列表
- 指定区域和时间范围的历史地震统计
- 震中分布图和报告生成

目录截止时间之后发生的新地震不会出现在结果中。离线包不会自动更新 USGS 数据；需要新目录时，请换用更新日期的离线包。

## 停止服务

关闭启动脚本打开的终端窗口，或在终端按 `Control+C`。网页随后无法访问属于正常现象。

## 常见问题

### 浏览器没有自动打开

保持启动窗口开启，手动访问：

```text
http://localhost:3100
```

### 端口 3100 已被占用

在解压目录运行：

```bash
PORT=3200 ./START-MAC-LINUX.command
```

然后访问 `http://localhost:3200`。

### 提示平台不匹配

这个包是 `Darwin-arm64`。出现平台不匹配说明当前机器不是 Apple Silicon Mac，需要使用对应平台的部署包。

### 提示缺少运行环境或地图依赖

包内文件可能没有完整复制或解压。删除当前解压目录，从原始压缩包重新完整解压，不要单独复制启动脚本。

### 生成结果中没有最新地震

这是离线目录截止时间造成的。先查看页面右上角的目录时间；超过该时间的事件需要使用更新版离线包或联网版。
