# 形序 · Xingxu Body Journal

一个在 Mac 和 Windows 电脑上运行的身体变化记录工具。红金色战甲风格界面，支持体脂秤截图识别、测量档案、趋势图、训练恢复日志和有依据的日常行动建议。

**每个人从空白档案开始，数据保存在自己的电脑上。** 不需要注册账号，不需要 API Key，截图识别与建议计算均在本机完成。

## 下载即用

### Mac

在 [Releases 下载页](https://github.com/G-lbx/xingxu-body-journal/releases/latest) 按芯片选择文件：

| 关于本机中显示的芯片 / 处理器 | 下载文件 |
| --- | --- |
| Apple M 系列芯片 | `XingxuBodyJournal-macOS-AppleSilicon.zip` |
| Intel 处理器 | `XingxuBodyJournal-macOS-Intel.zip` |

1. 双击 ZIP 解压，将 `XingxuBodyJournal.app` 拖到“应用程序”。
2. 双击应用，控制窗口会启动本机网页。使用期间请保留控制窗口。
3. 填写自己的个人档案，导入体测截图，核对日期与数字后保存。
4. 在控制窗口点击“停止并退出”结束使用，下次继续打开应用即可。

构建目标为 **macOS 13 或更新版本**，自动化验收在 macOS 15 的 Apple 芯片与 Intel 环境进行；其他系统版本尚未逐一实测。下载版内置运行环境，不需要安装 Python、Xcode 或配置 API Key。

当前版本尚未使用 Apple Developer ID 签名和公证，首次打开可能提示开发者无法验证。确认文件来自本仓库的 Releases 后，可按 [Apple 官方说明](https://support.apple.com/zh-cn/102445)，在尝试打开后进入“系统设置 → 隐私与安全 → 仍要打开”，仅批准这个应用。

### Windows

1. 在 [Releases 下载页](https://github.com/G-lbx/xingxu-body-journal/releases/latest) 下载 `XingxuBodyJournal-Windows-x64.zip`。
2. 将整个 ZIP 解压，保留同目录的 `_internal` 文件夹；双击 `XingxuBodyJournal.exe`。
3. 控制窗口会启动本机服务并打开浏览器。首次使用请在“个人档案”填写资料。
4. 点击“导入体测截图”，对照原图核对日期和数值，再确认保存。
5. 下次继续双击 EXE。需要退出时，在控制窗口点击“停止并退出”。

适用于 Windows 10/11 x64，**不需要安装 Python**。控制窗口提供“打开网页”“打开数据文件夹”和“停止并退出”。使用期间请保留控制窗口；只关闭浏览器不会删除数据。

程序只监听 `127.0.0.1`，默认从 8765 端口启动；被占用时尝试后续端口，实际地址显示在控制窗口。这是本机应用，不是公网网站。

## 功能

- **截图识别与核对**：JPG / PNG / WebP，单张最大 12 MB；Windows OCR / Apple Vision 本机识别；未可靠识别的字段留空，数字修正与缺失项会提示核对。
- **测量档案**：保存原图、手动录入、编辑、删除、相同时间和图片去重；可补充腰围与测量备注。
- **变化趋势**：体重、体脂率、肌肉量、骨骼肌量；7 天、30 天和全部记录；周均值与足够数据下的周对比。
- **真实与推算分开显示**：设备历史差值仅作为可追溯的空心参考点，不当成完整历史实测。
- **行动建议**：结合个人档案、测量记录和恢复情况计算，展示原因及公开来源。
- **训练与恢复日志**：运动类型、训练分钟、睡眠、步数、精力、饮食打卡、备注和每日任务。
- **备份恢复**：JSON 导出结构化数据，ZIP 完整备份包含原图；合并恢复保留已有记录并列出冲突。
- **动态界面**：红金主题、光标光效、按钮反馈和卡片光效，可关闭特效，尊重系统减少动画设置。

## 数据与分享

Windows 下载版的数据目录：

```text
%LOCALAPPDATA%\XingxuBodyJournal\data
```

Mac 下载版的数据目录：

```text
~/Library/Application Support/XingxuBodyJournal/data
```

两个系统均可通过控制窗口的“打开数据文件夹”定位。源码运行默认使用项目目录下的 `data`。

| 内容 | 文件或目录 |
| --- | --- |
| 测量、个人档案、训练日志 | `journal.sqlite3` |
| 原始截图 | `uploads/` |
| 每天首次修改前的数据库快照 | `automatic-backups/`，最多保留最近 7 份 |

自动快照仅包含数据库。迁移电脑或升级前，建议在页面导出**完整 ZIP 备份**。下载新版程序不会自动清除该数据目录。

仓库与程序包不包含使用者的数据库、体测截图、个人档案、日志或备份。分享给朋友时，直接分享 Releases 下载链接或原始程序 ZIP，避免把自己的数据目录一并打包。

## 识别与建议的适用范围

OCR 能力取决于系统本机的识别语言与图片清晰度，不同版式可能有遗漏；**确认保存前需要人工核对**。识别不可用时仍可上传原图并手动填数值。

建议由本机规则和公开健康资料计算，没有连接云端生成模型。体脂与肌肉量属于设备估算，短期读数会受水分及测量条件影响；记录不足时不判定已经减脂或增肌。个人资料不完整时先给基础建议，确认适用条件后再细化训练与营养参考。

设备 BMI 与档案计算结果明显不一致时，保留原值并提示核对设置。身体年龄不替代真实年龄，基础代谢估算不直接作为每日摄入目标。详细依据见 [健康资料说明](docs/health-sources.md)。

## 从源码运行

需要 Python 3.10 或更新版本。运行使用 Python 标准库与 Tkinter；Windows OCR 使用系统内置能力。Mac 源码运行需选择带 Tkinter 的 Python，并安装 Xcode Command Line Tools 后先执行 `bash scripts/build_macos_ocr.sh`，编译 Apple Vision 识别组件。下载版已包含组件。

```powershell
python desktop.py
```

也可以双击 `启动形序.cmd`，启动隐藏的本机服务，再用 `停止形序.cmd` 结束。纯服务方式：

```powershell
python server.py --port 8765
```

测试或多实例运行可指定独立数据目录：

```powershell
python desktop.py --port 8770 --data-dir .qa/manual --no-browser
```

## 测试

```powershell
python -m unittest discover -v
node --test test_chart.cjs
```

测试使用虚构样本和临时数据库，不修改个人档案。真实 OCR 原图测试默认跳过，可通过仓库外的私有清单单独启用，见 [测试与验收说明](docs/verification.md)。

## 构建 Windows 程序包

在 Windows x64 创建独立构建环境：

```powershell
python -m venv .venv-build
.\.venv-build\Scripts\python.exe -m pip install -r requirements-build.txt
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_windows.ps1
```

产物为 `dist/XingxuBodyJournal-Windows-x64.zip` 和同名 `.sha256` 校验文件。打包采用显式资源清单，不复制私人数据、体测原图或开发预览图。

## 构建 Mac 程序包

在目标架构的 Mac 上运行（Apple 芯片或 Intel）：

```bash
python3 -m venv .venv-build
.venv-build/bin/python -m pip install -r requirements-build.txt
bash scripts/build_macos.sh
```

构建需要 Xcode Command Line Tools 及带 Tkinter 的 Python。输出为 `dist/XingxuBodyJournal.app`、对应架构 ZIP 与 SHA256 文件。使用 `ditto` 打包以保留应用内的执行权限和符号链接。

仓库的 **Build and verify macOS apps** GitHub Actions 工作流可手动运行，在两种架构原生构建。工作流检查单元测试、Tkinter、应用代码签名完整性，以及内置环境下的实际 OCR、保存和重启；全部通过后才上传下载产物。生成的虚构测试图片留在 CI，不放入应用包。
