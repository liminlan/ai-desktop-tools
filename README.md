# AI 桌面小工具集

两个给 Windows 用的桌面小工具，都是「贴在屏幕边上、按一下就干活」的形态，不占任务栏、不打断你正在做的事。

| 工具 | 干什么 | 联网 | 目录 |
| --- | --- | --- | --- |
| **便携翻译** | 框选屏幕上的英文 → 本地 OCR → 本地神经翻译，全程离线 | 只有首次下载模型时联网 | [`offline-translator/`](offline-translator/) |
| **APL 视觉模型**（豆包截图挂件） | 点一下框选屏幕 → 自动发给视觉大模型 → 答案从挂件上方弹出 | 框选松手那一刻才上传那一小块图 | [`doubao-screenshot-widget/`](doubao-screenshot-widget/) |

---

## 1. 便携翻译 · offline-translator

纯本地的 Windows 取词翻译：截屏框选 → 系统 OCR → CTranslate2 神经翻译（en→zh），**不调用任何在线接口、不消耗任何 AI 额度**。

- `Alt+T` 唤起框选，`Ctrl+Alt+C` 直接翻剪贴板
- 圆形悬浮球 / 横条悬浮条，右键随时切换
- 界面米黄 + 浅绿 + 深绿，浅色简约风

👉 详细用法、技术栈、实测性能、目录结构见 [offline-translator/README.md](offline-translator/README.md)

> 打包后的完整程序约 547MB（含 Qt 运行时 + 模型），超过 GitHub 单文件 100MB 限制，所以仓库里只放源码 + 模型，需要 exe 按 README 第三节用 PyInstaller 自行打包。

## 2. APL 视觉模型 · doubao-screenshot-widget

一个紫色圆球挂件：点一下就能框选屏幕任何位置，自动发给免费视觉模型（智谱 `GLM-4.6V-Flash`，官方标注输入输出全免费），答案从圆球上方的小卡片弹出来。不用切窗口、不用复制粘贴。

- 单击圆球 → 拖框 → 松手即出答案；`Ctrl+Alt+Q` 老板键
- 平时缩成半圆贴边，鼠标靠近才展开
- 卡片里可以继续追问，AI 记得这张图
- 自带「存图」、听写按钮、把截图另存为原分辨率 PNG

![效果预览](doubao-screenshot-widget/效果预览.png)

👉 首次使用（拿 API Key、填 Key、自检命令）见 [doubao-screenshot-widget/README.md](doubao-screenshot-widget/README.md)

⚠️ 仓库里的 `config.json` 已经把 `api_key` 清空了，首次运行请自行填自己的 Key，不要把自己用的 Key 提交上来。

---

## 系统要求

- Windows 10 / 11（64 位）
- 便携翻译：无需 Python 可直接用打包版；源码运行需 Python 3.11~3.13
- 截图挂件：exe 版无需 Python；源码运行需 Python + Pillow

## 许可

代码可自由查看、修改、自己用。第三方模型与接口归各自平台所有（Argos/CTranslate2 语言包、智谱 GLM 接口），请遵守其条款。
