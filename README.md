# MiniMax Speech Skill

Text-to-speech (TTS) skill using the official MiniMax Speech 2.8 HD API, for Codex and Claude Code: custom voice design, authorized voice cloning, Chinese voiceover, speech direction, HTTP/WebSocket, subtitles, and encrypted local API credentials.

让 AI 使用 MiniMax 官方 **Speech 2.8 HD** 生成配音，把“声音提示词”落实为音色、情绪、语速、停顿、发音词典和支持的声音标签。支持**文字设计音色**、**参考音频复刻/声音克隆**、完整 HTTP 输出与标准 WebSocket，保存可复用音色档案、音频、字幕和实际参数。

这是独立开源项目，与 MiniMax 无隶属或背书关系。项目采用 [BSD Zero Clause (0BSD)](LICENSE) 许可，允许商用、修改和再分发，无署名保留条件。官方 API 服务单独计费，仍受 MiniMax 的服务条款约束；第三方依赖保留各自许可。

## 让 AI 安装

将**本仓库地址**发给有本地文件和执行能力的 AI，并附上：

> 请安装这个项目中的 minimax-speech 技能，先阅读 README.md 和 AGENTS.md，使用安装器完成安装。安装后主动引导我配置自己的 MiniMax 官方 API Key，通过本机隐藏输入并加密保存；如果我尚未注册，提供官方注册入口和教程。不要在安装时生成收费试听。

AI 应获取仓库文件、运行安装器，随后根据返回状态继续配置。单纯打开网页不会自动修改本机。安装完成但尚未提供密钥时，技能可发现，API 配置仍待完成。

## 本机安装

准备 Python 3.10+，下载仓库 ZIP 并解压，或克隆仓库。在项目目录运行：

```text
python install.py
```

默认安装到 `~/.agents/skills/minimax-speech`，为技能创建私有 Python 环境并安装依赖，然后在终端提示隐藏输入密钥。没有密钥可先按提示打开注册页面，或中断配置后再运行 `python <skill>/run.py configure`。

其他安装方式：

```text
# AI/自动化：只输出状态，不等待终端输入；AI 随后主动询问并引导
python install.py --non-interactive --json
# Claude Code 的技能目录
python install.py --agent claude
# 自定义 skills 父目录
python install.py --dest /path/to/skills
# 跳过依赖，供离线安装或自行管理运行环境
python install.py --no-deps --non-interactive --json
```

Windows 终端若使用 `py -3` 启动 Python，可将示例中的 `python` 相应替换。路径含空格时加引号。重复安装相同文件会复用；发现已有不同文件则拒绝覆盖。更新前保留已有技能副本，比较差异后再安装到空目录。不要复制旧 `.venv` 到新位置。

其他支持 `SKILL.md` 的工具也可复制 `skills/minimax-speech` 到其技能目录；需按教程补运行依赖并立即执行 `onboard`。工具自己的技能发现规则为准。Codex 目录依据：[官方 Skills 文档](https://developers.openai.com/codex/skills)。

## 密钥与注册

- [官方注册/登录](https://platform.minimax.cn/login?source=platform_docs)
- [创建按量付费 API Key](https://platform.minimax.cn/user-center/basic-information/interface-key)
- [本项目注册、配置与故障教程](skills/minimax-speech/references/setup.md)

Windows 使用 DPAPI，macOS 使用 Keychain，Linux 使用 Secret Service。密钥库不可用会明确提示，不降级为明文；Linux 无桌面会话时需先准备系统密钥库。密钥不会写入仓库、示例或生成记录。推荐本机隐藏输入，避免经过聊天。

安装和保存密钥不调用语音 API。`ready` 表示本机可读取凭据，官方鉴权尚未验证；用户明确要求配音或测试后才生成。删除本机凭据使用 `forget-credential`，官方吊销请在平台后台操作。

## 使用

安装后直接告诉 AI：

> 用 MiniMax Speech 给这段文字配音：自然亲切、稍慢一点，欢迎语后停顿半秒。保留原文，输出音频和字幕。

普通 TTS 没有独立的自然语言 `prompt` 字段，技能会将声音要求转换为受支持的参数与标签，不把指令读出来。详见 [声音控制](skills/minimax-speech/references/speech-direction.md) 与 [API 和输出](skills/minimax-speech/references/api.md)。

手动调用时，将 `<skill>` 换成安装输出显示的目录：

```text
python <skill>/run.py onboard
python <skill>/run.py voices --out voices.json --search 亲切
python <skill>/run.py preview --job job.json
python <skill>/run.py generate --job job.json --out takes/take-01
```

从 [job.example.json](skills/minimax-speech/references/job.example.json) 复制任务示例，确认当前账号可用音色后使用。每次生成使用新的输出目录，避免覆盖结果。WebSocket MP3/FLAC 合并需要本机 FFmpeg；HTTP 与 WebSocket PCM 不需要。

## 自定义角色声音

可以告诉 AI：“根据角色设定设计一个清亮、自然的年轻成年女声，生成一段试听并保存音色ID。”也可以提供自己有权使用的录音，要求复刻并复用。单纯安装技能不会上传录音或生成付费试听。

从 [音色设计示例](skills/minimax-speech/references/voice-design.example.json) 或 [音色复刻示例](skills/minimax-speech/references/voice-clone.example.json) 开始。复刻前需要官方个人/企业认证，主参考为10秒至5分钟的 MP3/M4A/WAV，每个文件不超过20MB；实际取得素材授权后才能将示例的 `authorized` 改为 `true`。

```text
python <skill>/run.py voice-design --job design.json --dry-run
python <skill>/run.py voice-design --job design.json --out voices/design-01
python <skill>/run.py voice-clone --job clone.json --dry-run
python <skill>/run.py voice-clone --job clone.json --out voices/clone-01
python <skill>/run.py generate --job narration.json --profile voices/design-01/profile.json --out takes/take-01
```

`--dry-run` 不读取密钥、不联网。新音色目录的 `profile.json` 可直接用于后续配音；任务中不要再填写旧音色ID，以免覆盖该档案。支持可选短示例音频、对应文本、降噪、音量归一化与 ASR 文本校验，详见 [音色创建与复刻说明](skills/minimax-speech/references/voice-creation.md)。

MP3/M4A 复刻素材的时长校验需要 FFprobe；PCM WAV 无需额外工具。复刻音色7天内未正式调用会被官方删除，不会为保活自动生成音频。

## 更新安装

安装器保护已有不同文件。更新前将旧技能目录备份到技能发现目录之外，例如 `~/.claude/skill-backups/minimax-speech-<timestamp>`，检查并保留个人修改，再安装到原来空出的路径。不要把备份留在活动的 `skills` 内，避免发现两份技能；不要搬用旧 `.venv`。

Claude Code 可运行 `python install.py --agent claude --non-interactive --json`；Codex 若先前安装在自定义目录，应继续使用原来的 `--dest`，避免重复安装。Windows 同用户的 DPAPI 凭据保存在技能外部，更新时会复用，不要导出到仓库。安装完成运行 `onboard --json`，`ready` 时无需重新索取密钥。

## 范围与验证

TTS 和复刻试听固定 `speech-2.8-hd`，音色设计使用不含模型选择字段的官方专用接口；不自动降级、不自动重试结果未知的收费请求。当前未实现异步长文、HTTP SSE和混音。音色与自然度需要用户试听。

维护者于 2026-10-18 完成过官方 HTTP 和 WebSocket 真实调用测试。公开测试使用模拟响应和虚构凭据，不包含真实密钥、音频或账号记录。Windows 加密往返可本机验证；macOS/Linux 后端有模拟测试，实际系统密钥库仍需对应平台实测。

v1.1.0新增音色设计、文件上传与复刻；2026-10-19按官方文档实现并完成模拟响应测试，本次未调用收费创建接口，真实音色效果与账号权限待用户实际任务验证。

v1.1.1修正了测试对 Windows 短路径和 macOS 目录别名的比较，使用文件身份核对实际传给 FFprobe 的素材；接口调用行为不变。

无需 API 密钥的测试与发布检查：

```text
python -m pip install -r skills/minimax-speech/requirements.txt
python -m unittest discover -s tests -v
python tools/check_release.py
```

[GitHub 发布教程](docs/publishing.md)包含网页上传、命令行推送、Release ZIP 和安装验收方法。

参考：[MiniMax 官方接口文档](https://platform.minimax.cn/docs/guides/speech-t2a-websocket)；研究时也参考了 [minimax-speech-studio](https://github.com/buxiangyaohaoming/minimax-speech-studio) 的交互需求，本项目不打包其源码。
