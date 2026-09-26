# 安装引导

## 下载与解压

在仓库页面选择 **Code → Download ZIP**，或由朋友把同一份 ZIP 发给你。先完整解压，再运行里面的程序，不要在压缩包窗口内直接双击。推荐放到 `D:\QuestionBank` 等固定目录。

这是源码安装包：首次安装仍需联网下载依赖；把 ZIP 发给朋友不代表可以断网安装。当前脚本已完成本地模拟及回归检查，尚未在 Windows 实机验收。

## Windows 10/11 x64

### 第一步：安装基础软件（只需一次）

- [Python 3.11](https://www.python.org/downloads/release/python-3119/)：选择 Windows installer (64-bit)，安装时保留 Python Launcher，并勾选 Add python.exe to PATH。
- [Node.js](https://nodejs.org/en/download)：选择 22.12 或更高版本的 LTS 安装包，保留 npm 组件。
- [OpenCode CLI](https://opencode.ai/docs/)：已有命令行版本可跳过。在终端运行 `opencode --version` 应能显示版本。只有桌面版但此命令无效时，在安装 Node.js 后运行 `npm install -g opencode-ai`。
- [LibreOffice](https://www.libreoffice.org/download/download-libreoffice/)：旧 Word 公式、矢量图和组合图可能需要，建议安装。普通网页浏览无需 Microsoft Word。

安装完成后关闭并重新打开终端/脚本窗口，以读取新环境。**不需要 Codex。**

### 第二步：双击 `01-install.cmd`

程序会检查 Python 和 Node.js，征得确认后安装 Python 依赖并构建网页。失败即停止；修复网络或依赖后可重新运行，不删除你的数据。正常结束后窗口显示“安装完成”。

### 第三步：双击 `02-setup-api.cmd`

1. 检查 OpenCode 是否能运行，是否支持题库所需调用参数。
2. 若已在 OpenCode 配好模型账户，可跳过登录；否则进入官方登录引导，使用自己的 API 凭据。
3. 从程序列出的 DeepSeek 模型中选择题库已适配的模型，输入完整名称。模型列表本身不证明账户有权限或有余额。
4. 同意后仅发送一次简短文字连接测试，可能产生少量费用，超时不自动重试。通过才保存本机题库设置，原设置会备份。

**如果没有列出受支持的模型，或提示缺少调用参数，请先停止并联系维护者。** 当前正式流程针对已适配的 DeepSeek 模型，不承诺所有 OpenCode 服务商或纯文字模型都能直接用于图片题目。官方登录说明：[OpenCode CLI](https://opencode.ai/docs/cli/#login)。

此测试只验证文字请求；首次使用先导入一页有题图的小样例，核对公式、图片和表格。PDF/质量审查流程也可能直接读取本机 OpenCode 的 DeepSeek 凭据调用官方 API，因此需实际的 DeepSeek API 权限，其他服务商登录不能替代。

### 第四步：双击 `03-start.cmd`

启动完成后自动打开 http://127.0.0.1:8765/ 。请保留窗口，停止时按 Ctrl+C。首次启动是空题库，试卷放入同目录 `materials` 文件夹，也可从网页上传。

以后通常只需要双击 `03-start.cmd`。更换模型账户时再运行 API 引导。

## 常见问题

| 现象 | 处理方法 |
| --- | --- |
| 无法连接 GitHub | 让朋友转发完整 ZIP；首次依赖安装仍需要联网。 |
| 安装下载失败 | 检查网络/代理后重新运行。脚本不会擅自修改系统代理或切换镜像。 |
| 找不到 Python | 安装 Python 3.11 x64，并包含 Python Launcher；重新打开脚本窗口。 |
| 找不到 OpenCode | 确认安装的是 CLI，终端能执行 `opencode --version`。 |
| API 测试失败 | 核对所选模型权限、API 余额及网络。不必删除题库重装。 |
| 端口被占用 | 检查题库是否已经启动；关闭重复实例，不会自动终止其他程序。 |
| 旧 Word 图片读取失败 | 安装 LibreOffice；非标准目录可设置 `QUESTION_BANK_SOFFICE` 为 soffice.exe 的完整路径。 |
| 字体与别人的电脑不同 | 请使用合法安装的宋体、Times New Roman、Cambria Math；安装包不附带商业字体。 |

## macOS

先安装 Python 3.11、兼容的 Node.js、OpenCode CLI 和需要的 LibreOffice。在项目目录执行：

```sh
sh install.sh
PYTHONUTF8=1 .venv/bin/python scripts/setup_opencode.py
sh start.sh
```

macOS 启动脚本不会自动打开浏览器，请自行访问 http://127.0.0.1:8765/ 。

## 本机数据与更新

- 数据在 `data/`，原卷在 `materials/`；API 设置及凭据留在本机。模型识别会把所选题目和图片发给相应服务商。
- 安装脚本不上传本机题库，不自动更新，不迁移或替换你的数据。
- 以后接收新版程序前先备份 `data/`、`materials/`、本机 `config.json`。目前没有自动更新功能，按维护者提供的更新说明操作。
- 仅用于本机。不要将端口直接开放到互联网。

## OpenCode 引用

本项目不是 OpenCode 官方产品。OpenCode CLI 由使用者独立安装；本项目改编的历史提示词已在 `THIRD_PARTY_NOTICES.md` 中注明来源并保留上游 MIT 声明。
