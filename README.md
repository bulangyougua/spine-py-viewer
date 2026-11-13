# Spine 动画查看器

在本地打开一个文件夹，播放里面的 Spine `.skel` 和 `.json` 动画。同一个名字的两种文件会各占一行，并配上同目录的 `.atlas` 和图片。

## 使用

双击 `SpineViewer.exe`，或把文件夹拖到 exe 上。也可以先打开程序，再点「打开文件夹」。上次打开的文件夹会记在 `%APPDATA%\spine-py-viewer\settings.json`。

- 列表显示文件名、所在目录、`skel` / `json` 和 Spine 版本。
- 打开后从第一个动画开始，每段播完自动播下一段，播完再从头循环。
- 「暂停 / 继续」暂停骨架。「循环播放」从第一个动画重新串起来。点某个动画按钮只播这一段。
- 「预乘 Alpha」按贴图需要开关。画面发白或发暗时可以换一下。
- 右下角可以缩放画布：`+` / `−`、滚轮（以鼠标位置为中心）、拖动平移。点百分比、双击画面或按 `0` 会重新适应画面。键盘 `+` / `−` 同样可用。空格键暂停。

打开时会按当前动画的范围居中。动画不在画面中心、或特别大特别小时，用缩放和平移调整。缩放范围是 8% 到 1600%。

## 能播放的版本

| 版本 | 文件 |
| --- | --- |
| 2.1 | json |
| 3.6 | json |
| 3.7 | json |
| 3.8、4.0、4.1、4.2、4.3 | skel 和 json |

版本按文件头里的 `主版本.次版本` 选择对应运行时，不会用别的版本硬解。2.1 的 mesh 附件不会绘制，区域贴图可以正常显示。

## 从源码运行

需要 Python 3.11 或更高版本，并且带 tkinter。运行时不安装第三方 Python 包。

```bat
python main.py
python main.py D:\path\to\spine-folder
python main.py --scan D:\path\to\spine-folder
python main.py --no-browser --port 8765 D:\path\to\spine-folder
```

`--scan` 只打印找到的骨架后退出。`--no-browser` 只启动本机页面，不打开窗口。

打包成单个 exe（需要 `pip install -r requirements.txt`）：

```bat
build.bat
```

生成的 `SpineViewer.exe` 在项目目录里。`vendor/` 里是随程序分发的官方 Spine 运行时。需要重新下载时运行 `python fetch_runtimes.py`。

## 许可

查看器源码随本仓库提供。`vendor/` 与 `SPINE-RUNTIMES-LICENSE.txt` 是 Esoteric Software 的 Spine Runtimes，使用和再分发须遵守该许可：https://esotericsoftware.com/spine-editor-license
