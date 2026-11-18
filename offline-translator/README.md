# 离线翻译悬浮窗

一个纯本地的 Windows 桌面取词翻译工具。截图框选 → 本地 OCR → 本地神经翻译，**全程不联网、不调用任何在线接口、不消耗任何 AI 额度**。

- 界面：浅色简约，米黄 + 浅绿 + 深绿
- 形态：圆形悬浮球 / 横条悬浮条，右键随时切换
- 主操作：`Alt+T` 唤起 → 拖动划选英文区域 → 松开即出译文
- 兼容操作：`Ctrl+Alt+C` 直接翻译剪贴板；开启后复制英文自动译

---

## 一、直接用（exe 版）

1. 解压整个 `OfflineTranslator` 文件夹（**不要只把 exe 单独拷出来**，模型和依赖都在同目录）
2. 双击 `OfflineTranslator.exe`
3. 右下角托盘出现「译」图标，屏幕左边出现米黄色悬浮球

首次启动若检测不到模型，会弹窗问你是否下载（约 70MB，只这一次联网）。下载完就永久离线。

## 二、从源码跑

```powershell
# 1. 建环境（Python 3.11~3.13 都行，实测 3.13）
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r offline-translator\requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 2. 下载模型（约 70MB，只跑一次）
.venv\Scripts\python.exe offline-translator\scripts\download_models.py

# 3. 自测引擎能不能跑（不弹界面）
.venv\Scripts\python.exe offline-translator\scripts\selftest.py
.venv\Scripts\python.exe offline-translator\scripts\validate.py

# 4. 启动
.venv\Scripts\pythonw.exe offline-translator\main.py
```

## 三、打包成 exe

```powershell
.venv\Scripts\python.exe -m pip install pyinstaller
.venv\Scripts\pyinstaller.exe --noconfirm --clean offline-translator\build.spec
```

产物在 `dist\OfflineTranslator\`。把 `offline-translator\models\` 整个文件夹拷到 `dist\OfflineTranslator\models\`（模型外置，不打进 exe，方便替换和升级）。

---

## 四、怎么用

| 操作 | 效果 |
|---|---|
| 鼠标左键单击悬浮球 | 进入框选模式 |
| `Alt+T` | 同上，不用去点悬浮球 |
| 框选后松开鼠标 | 立即识别 + 翻译，结果窗贴在你选的位置 |
| `Ctrl+Alt+C` | 直接翻译剪贴板里的英文 |
| 右键悬浮球 / 托盘图标 | 菜单：框选、翻译剪贴板、切换形态、设置、退出 |
| 拖动悬浮球 | 换位置，松手贴边自动对齐，位置会记住 |
| 结果窗 | 可拖动；`Esc` 关闭；「复制译文」一键复制；「重译」重新跑一遍 |
| 设置里 | 热键、悬浮形态、字号、结果窗宽度、计算设备、开机自启、清缓存 |

**小细节**：框选时可以框一整段（多行），程序会自动把 OCR 断开的行拼回完整句子再翻译。这是离线翻译质量的关键一步，不然一句话会被切成好几截碎片。

---

## 五、技术栈与体积

| 环节 | 方案 | 体积 |
|---|---|---|
| 界面 | PySide6 (Qt6) | 打包后约 60~90MB |
| OCR（默认） | Windows 系统自带 OCR（WinRT `Media.Ocr`） | **0 MB**，系统自带，不用下模型 |
| OCR（兜底） | RapidOCR（PP-OCR 的 ONNX 版） | 约 30MB 安装 + 13MB 模型 |
| 文本修复 | wordninja（离线英文词频表） | 约 3.4MB |
| 翻译 | CTranslate2 + Argos en→zh 语言包 | 模型约 70MB |
| 缓存 | SQLite | KB 级 |

两个关键取舍：

1. **没有装 `argostranslate` 这个库**。它硬依赖 stanza → torch，光依赖就 2GB 以上，而我们要的只是它语言包里的 CT2 模型和分词模型，自己用 ctranslate2 + sentencepiece 加载就够，省掉整条 torch 依赖链。
2. **默认取词用 Windows 系统 OCR，不用 RapidOCR**。实测同一张 1375×475 的截图：系统 OCR 8~117ms，RapidOCR 1.6~2.4 秒（慢 20 倍以上，瓶颈在文本检测把短边放大到 5888px）；而且 RapidOCR 的中文识别模型对英文会丢空格，对翻译是灾难。系统 OCR 只在中文版 Windows 上装了 `zh-Hans-CN` 语言包，但识别英文完全够用（中英混排的标题栏会被当作噪声行过滤掉）。RapidOCR 保留作为兜底，系统 OCR 不可用时自动切换。

---

## 六、实测性能（i5-11400 / 16G / CPU 推理）

| 环节 | 耗时 |
|---|---|
| 翻译模型加载 | ~0.4s（启动时后台预热，用户无感） |
| 单句翻译 | 50~100ms |
| 缓存命中 | <5ms |
| 系统 OCR（一行小图） | 8~53ms |
| 系统 OCR（一整段 1375×475） | ~117ms |
| 整链路（首次含引擎初始化） | 0.7~1.1s |
| 整链路（引擎已热） | 150~250ms |

> 框得越大越慢。框一条字幕/一行文字最快。

---

## 六点五、OCR 结果为什么要「修文本」

Windows OCR 对英文有三种典型损伤，不修会直接把错误喂给翻译模型：

| 现象 | 例子 | 修复方式 |
|---|---|---|
| 单词被粘成一团 | `lOtover`、`pastfew`、`goodenough` | 用 wordninja 词频表把长词切开 |
| 单词被切出空格 | `imp roved`、`yea rs`、`a re`、`netwo rk` | 两段拼起来是词典里的真词就粘回去 |
| 大小写抖动 | 句子中间冒出 `lOt` | 短词内部大写转小写 |

判断「拼起来是不是真词」很关键：`a lot` 拼成 `alot` 词典里没有，所以正常双词不会被误合并；`in fact` 拼成 `infact` 同理。实测这套规则对正常英文句子**零改动**，只动真被 OCR 弄坏的地方。

另外，窗口标题栏、中文菜单栏会被识别成乱码（`讠 己 事 本`），这类中英混排的噪声行会被直接过滤掉，不会进译文。


---

## 七、常见问题

**Q：托盘没有图标 / 悬浮球不见了？**
Windows 10 的托盘默认会把新图标收进「^」折叠区，点开看一下；或者在设置里重新打开。

**Q：热键按了没反应？**
`Alt+T` 可能被别的软件（截屏工具、输入法、游戏）占用。启动时如果注册失败，托盘点会弹出提示告诉你哪个热键冲突了，去设置里换一个，**改完热键要重启程序**。

**Q：框选了但提示「这块区域里没有英文」？**
OCR 只认文字，图片里的花体字、手写体、极小的字（<10px）识别率会掉。选中后如果框太窄，程序会漏字，框宽一点。

**Q：翻出来的中文有点生硬？**
这是离线小模型的固有上限（en→zh 模型只有 70MB，参数量远小于在线大模型）。定位是「读英文资料/看视频够用」，不是「出版级翻译」。想更好就得换本地大模型，代价是 1GB+ 体积和每句几秒的延迟。

**Q：杀毒软件报毒？**
PyInstaller 打包的 exe 常被误报（因为打包器特征）。加白名单即可；源码完全开源，可以自己审。

**Q：能翻中文→英文吗？**
当前只做英→中。中文内容会被识别出来并提示「不需要翻译」，不会输出乱码。

**Q：我的配置文件在哪？**
程序目录下的 `config.json`；缓存是 `cache.db`；日志 `app.log`。删掉 `cache.db` 等于清空翻译缓存。

**Q：为什么我把程序放在中文目录下也能用？**
CTranslate2 和 SentencePiece 的 C++ 层打不开含中文的路径（会报 NOT_FOUND，即使文件就在那儿）。程序检测到这种情况会自动把 `models` 复制到 `C:\ProgramData\OfflineTranslator\models` 并从那里加载，第一次启动会多花几秒。想省掉这一步，就把程序放到纯英文路径下。

---

## 八、目录结构

```
offline_translator/
├─ main.py                  入口：单实例、组装、热键、剪贴板
├─ core/
│  ├─ config.py             JSON 配置（容错：坏了自动备份重建）
│  ├─ hotkey.py             RegisterHotKey + 独立消息线程
│  ├─ autostart.py          开机自启（写注册表 HKCU Run）
│  └─ model_manager.py      模型探测 / 下载 / 路径解析
├─ services/
│  ├─ ocr_engine.py         取词：Windows 系统 OCR（默认）+ RapidOCR（兜底）
│  ├─ textfix.py            OCR 英文修复：粘连切分、碎片合并、噪声行过滤
│  ├─ line_merge.py         OCR 行 → 段落合并（质量关键）
│  ├─ translation.py        CT2 + SentencePiece 推理 + 输出清洗
│  ├─ cache.py              SQLite 翻译缓存
│  └─ pipeline.py           门面：图/文 → 结果
├─ ui/
│  ├─ theme.py              配色与 QSS
│  ├─ floating.py           悬浮球 / 悬浮条
│  ├─ capture_overlay.py    全屏框选（多屏 + DPI 高清裁剪）
│  ├─ result_popup.py       结果卡片
│  ├─ settings_dialog.py    设置
│  ├─ tray.py               托盘
│  └─ workers.py            后台线程池
├─ scripts/
│  ├─ download_models.py    首次下载模型
│  ├─ selftest.py           引擎自测
│  └─ validate.py           门面自测（语言拦截/缓存/耗时）
├─ models/                  外置模型（不打包）
├─ build.spec               PyInstaller 配置
└─ requirements.txt
```

---

## 九、已知限制（说在前面）

1. **只支持英→中**。日→中、中→英需要另外的语言包，框架已留接口（`translation.py` 的 `TARGET_PREFIX_CANDIDATES` 和 `BACKEND_NAME`）。
2. **单词翻译不专业**。没有内置离线词典，单词也走神经翻译，所以 `hello` → 「哈罗」这种音译会出现。要专业查词得挂 ECDICT（约 100~400MB），没做。
3. **不做「区域定时自动识别」**。这是你明确否掉的 C 档（框定区域后每 2 秒自动重识别）。
4. **全屏独占游戏抓不到**。这类场景要用 DXGI 抓帧，没做。
5. **OCR 对极小字号和竖排文字不友好**（10px 以下掉识别率明显）。
6. **文本修复是启发式，不是万能的**。`readEnglish` 这种 OCR 把两词粘成一个且首字母小写的情况，会被切开但丢掉 `English` 的大写；真正生僻的专有名词（词典里没有的）也可能被误切。修的是常见损伤，不是全部。
