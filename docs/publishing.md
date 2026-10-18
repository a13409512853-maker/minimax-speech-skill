# GitHub 发布教程

发布目录是本文件的上一级，即包含 README.md、AGENTS.md、install.py、skills、tests 的项目根目录。**只上传这个目录里的项目文件**，不要上传开发工作区、历史测试、个人配置或现有已安装技能目录。

## 网页发布

1. 登录 GitHub，点击 New repository。建议名称 `minimax-speech-skill`，选择 Public。项目已经带 README、0BSD LICENSE 和 .gitignore，创建空仓库即可，不勾选自动生成这些文件。
2. 在空仓库页选择 uploading an existing file。将**项目根目录内的内容**上传，保持 skills、docs、tests 等目录结构；不要再套一层项目文件夹。
3. 确认 README.md 和 install.py 直接位于仓库根目录。网页拖放通常不显示点开头文件，务必确认 `.gitignore` 和 `.github/workflows/tests.yml` 也上传成功；不方便上传隐藏文件时使用下节 Git 方法。
4. 提交后阅读网页 README，确认相对链接可打开。无需在 README 里填写任何 API Key。

## 简介与检索

建议仓库简介：

> MiniMax Speech 2.8 HD TTS skill for Codex & Claude Code | Voice design & cloning | 中文配音、音色设计与声音复刻 | HTTP/WebSocket, subtitles, encrypted local API keys.

首页 About 旁的齿轮可以修改简介和 Topics。建议标签：

`minimax`、`minimax-speech`、`text-to-speech`、`tts`、`speech-synthesis`、`voice-design`、`voice-cloning`、`ai-skills`、`codex`、`claude-code`、`voiceover`、`python`、`websocket`、`chinese-tts`。

名称、简介、README 与标签应准确描述项目，便于用户发现；GitHub 和外部搜索引擎的收录时间及排序无法保证。可用 `minimax-speech-skill` 或 `minimax speech tts skill` 检索，也可直接分享完整仓库地址。

## 开源许可

本项目的原创代码与文档使用 BSD Zero Clause (SPDX: `0BSD`)。它允许商用、修改与再分发，没有署名保留条件，详见根目录 LICENSE。第三方依赖许可和 MiniMax API 服务条款独立适用。

## Git 推送

先在 GitHub 建立同名空仓库。在项目根目录打开终端：

```text
git init
git branch -M main
git add README.md AGENTS.md LICENSE .gitignore install.py docs skills tests tools .github
git status --short
git diff --cached --stat
git commit -m "Release MiniMax Speech Skill"
git remote add origin https://github.com/YOUR_GITHUB_USERNAME/minimax-speech-skill.git
git push -u origin main
```

将 `YOUR_GITHUB_USERNAME` 换成你的 GitHub 用户名。以上是发布者操作教程；不要把占位地址当成已存在的仓库。公开项目无需在源码保存 GitHub token。Git 身份未配置时按本人的 GitHub 身份设置，不能使用作者猜测的姓名或邮箱。

推送前运行：

```text
python -m pip install -r skills/minimax-speech/requirements.txt
python -m unittest discover -s tests -v
python tools/check_release.py
```

检查器会拒绝常见凭据模式、本机绝对路径、音频和构建残留，但它不能识别所有格式的秘密，仍应检查暂存文件。若曾把真实密钥提交到任何 Git 历史，删除当前文件仍不够；先在官方后台撤销，再处理历史。这个新项目目录不含旧开发历史。

## GitHub Release

本次版本标签为 `v1.1.1`。代码通过检查并提交后进入仓库 Releases，在对应提交上创建该标签的 Release，说明：

> 新增官方文字音色设计、参考音频上传与授权复刻，保存可复用音色配置。保留 Speech 2.8 HD、HTTP/WebSocket、声音控制、字幕和本地系统加密凭据。首次使用需要自己的官方 API Key；附件不含维护者密钥。41项本机测试通过，本次未调用收费创建接口。Windows 加密已验证，macOS/Linux 实际密钥库仍待对应平台验证。

v1.1.1还修正了 Windows 短路径、macOS 目录别名导致的测试误报；不覆盖或移动已发布的 v1.1.0 标签与附件。

可以使用 GitHub 自动生成的 Source code ZIP，或构建带 SHA256 清单的附件：

```text
python tools/check_release.py --zip dist/minimax-speech-skill-v1.1.1.zip
```

上传 ZIP 及旁边生成的 `.sha256` 文件。生成的 `RELEASE-MANIFEST.json` 位于 ZIP 内，列出发布文件的相对路径和 SHA256。不要上传本机 `.venv`。

## 安装验收

1. 从 GitHub 下载 Source code ZIP，解压到一个新目录。
2. 在新的临时 skills 父目录验证安装：

   ```text
   python install.py --dest ./installation-check --non-interactive --json
   python ./installation-check/minimax-speech/run.py onboard
   ```

3. 在干净账号上应返回 missing、注册入口和教程；已有密钥的账号返回 ready。unavailable 表示密钥库/依赖/权限需要处理，不能视为 missing。
4. 将真实仓库地址与 README 中的安装指令发给 AI，观察它是否读 AGENTS.md、运行安装器，并主动引导你隐藏输入密钥。AI 需要本地执行和写入技能目录的权限；仅网页浏览不足以完成安装。
5. 配置后检查本机可读状态。只有在你主动要求测试时，才生成短音频并试听。不要为了验收重复生成长文。

临时验收目录用完后在本机删除，不提交仓库；它包含本机运行环境。若同时保留正式技能和验收副本，避免把两份都放在 AI 会扫描的目录内。

## 后续维护

修改文件后重复运行测试和发布检查，使用新版本标签。凭据保存位置独立于技能目录，更新不会把凭据带入仓库。安装器拒绝覆盖不同文件：保留用户原技能副本，检查差异，在空目录重新安装并重建依赖。不要删除用户凭据来解决普通更新问题。
