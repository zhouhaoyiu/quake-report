# 地震报告系统一键启动包

解压后不要移动包内文件。macOS Apple Silicon 离线包已经包含网页服务、Node.js、Python/Cartopy、Natural Earth 与国内边界数据、USGS 本地库、LibreOffice 和当前项目代码，不会联网下载数据或依赖。

## macOS

双击 `START-MAC-LINUX.command`

如果 macOS 提示无法打开，右键点这个文件，选择“打开”。

## Windows / Linux

Windows 和 Linux 需要各自平台的离线包，不能直接使用 macOS 包里的 Python/Cartopy 运行时。

启动成功后浏览器会自动打开：

`http://127.0.0.1:3100`

关闭启动窗口即可停止服务。

离线目录的截止时间显示在页面右上角。Event ID、近期事件和历史统计都从包内目录读取；超过截止时间的新事件不会出现在离线结果中。
