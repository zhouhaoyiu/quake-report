# 地震报告系统一键启动包

这个包用于有外网的 Windows x64 或 Linux x64 机器。包内包含当前代码、完整地图数据、USGS 本地库、Node.js 安装包和 Miniforge 安装包。首次启动会联网安装 npm/conda 依赖并构建项目；每次启动会先增量同步 USGS 目录，之后复用本地运行环境。

## Windows x64

双击 `START-WINDOWS.bat`

## Linux x64

在解压目录运行：

```bash
./START-LINUX.sh
```

启动成功后浏览器打开：

`http://localhost:3100`

关闭启动窗口即可停止服务。

地图、Word 和目录 CSV 可直接生成。PDF 转换需要系统已经安装 LibreOffice；未安装时仍可正常使用其他输出。
