---
name: minimax-speech
description: Generate speech with the official MiniMax Speech 2.8 HD API, design custom voices from text, or clone an authorized reference voice. Translate voice direction into supported controls; preserve reusable voice profiles, audio, subtitles, and usage records.
---

# MiniMax Speech

把用户的正文和声音要求转成可追溯的配音，也可设计新音色或复刻有权使用的参考声音。TTS 和复刻试听固定使用官方 `speech-2.8-hd`；音色设计接口没有模型选择字段。

## 安装后与首次使用

安装完成后立即运行 `python <skill>/run.py onboard --json`。每次需要调用 API 前检查凭据；本地可读只表示配置完成，不代表官方鉴权成功。

- `ready`：继续用户请求，不重复索取密钥。安装请求本身不授权生成付费试听。
- `missing`（退出码2）：主动告诉用户需要其自己的 MiniMax 官方按量付费 API Key，并询问是否已准备好。同步提供返回的注册与密钥页面，以及 [注册与配置教程](references/setup.md)；不要止步于“安装成功”。
- `unavailable`（退出码3）：先解决系统密钥库锁定、依赖或执行权限问题，不能将其误判为没有密钥并覆盖。
- 优先打开用户能操作的本机终端，运行 `python <skill>/run.py configure` 进行隐藏输入。若用户主动在对话中提供密钥，只在工具有保密输入或可信进程标准输入能力时通过 `configure --stdin` 传递；不能把值写入命令、参数、临时文件、日志或仓库。没有这种能力时请用户使用隐藏输入，不能声称已保存。
- 取得密钥后加密写入并读回验证；随后检查 `credential-status --json`。除非用户要求测试，不发送生成请求。已授权测试时先预览一次短稿再生成，避免重复计费。

## 执行

- 先读 [speech-direction.md](references/speech-direction.md)，将正文与声音要求分开。保留原稿；用户要求逐字朗读时，不改写措辞。普通 TTS 没有 `prompt` 字段，声音要求不能直接拼进正文。
- 首次使用、变更接口或排查问题时读 [api.md](references/api.md)。使用 `run.py` 入口，不要临时重写鉴权和流式收尾。
- 按用户声音偏好查询官方音色；已有明确的可用 `voice_id` 可直接复用。没有偏好时可用已验证的系统音色做短试听。未明确要求时，不创建或复刻音色。
- 为本次任务写 JSON；可从 [job.example.json](references/job.example.json) 开始。自然语言要求放 `direction`，原稿放 `original_text`，实际送读稿放 `text`；WebSocket 分段使用 `segments`。
- 先运行 `preview --job ...`，检查实际送读稿、模型、音色、参数和合并后的发音词典。用户已要求生成或测试时，完成预览即可继续执行，不增加重复确认。
- 通常用 HTTP 得到完整文件和字幕；需要分句流式输入时用 WebSocket。生成命令必须指定新的输出目录，避免覆盖历史结果。
- 检查 `job.json`、音频可解码性、字幕时长和缺失项。将音频提供用户试听；技术检查通过不能替代听感确认。

```powershell
python <skill>/run.py onboard --json
python <skill>/run.py voices --out <workspace>/voices.json --search 青涩
python <skill>/run.py preview --job <workspace>/job.json
python <skill>/run.py generate --job <workspace>/job.json --out <workspace>/take-01
```

复用参数时用 `--profile profile.json`，追加词典用 `--dict dictionary.json`，均可多次指定。同词不同读法会报冲突，先解决再发送。实际请求以预览和 `request.json` 为准，不能只确认词典被保存。

## 设计与复刻音色

用户明确要求新音色、角色声音设计或参考音频复刻时，先读 [voice-creation.md](references/voice-creation.md)，再选对应命令。只要求补充接口或安装技能时，不创建音色或上传个人录音。

- `voice-design`：把语言、年龄感、音色质感和表达方向写入 `prompt`，将最多500字的试听台词放入 `preview_text`；两者不能混为普通 TTS 的正文。
- `voice-clone`：确认用户有权上传并复刻素材后记录 `authorized: true`；检查主参考10–300秒、可选示例短于8秒，每个文件不超过20MB。WAV 可直接校验，MP3/M4A 需要 FFprobe。相对音频路径以任务 JSON 所在目录为基准。
- 先 `--dry-run`，本地检查不读密钥、不联网。用户已要求创建或复刻时可接着执行；未授权素材或缺少实际生成请求时不自行设置授权或提交。
- 返回目录内的 `profile.json` 可直接传给普通 TTS 的 `--profile`，继续调语速、音高、情绪和发音；这不是训练模型。音色设计的修改需要新一次设计，不能把修改描述作为 TTS 的 `prompt` 发送。
- 保存音色ID、脱敏响应、试听和上传编号。试听下载失败时复用已创建的音色，不重复复刻。官方说明复刻音色若7天内未正式调用会被删除；提醒用户，但不为保活自行生成付费音频。

```text
python <skill>/run.py voice-design --job design.json --dry-run
python <skill>/run.py voice-design --job design.json --out voices/design-01
python <skill>/run.py voice-clone --job clone.json --dry-run
python <skill>/run.py voice-clone --job clone.json --out voices/clone-01
python <skill>/run.py generate --job narration.json --profile voices/design-01/profile.json --out takes/take-01
```

## 凭据与结果

`configure` 使用 Windows 当前用户 DPAPI、macOS Keychain 或 Linux Secret Service 加密保存，细节见配置教程。系统密钥库不可用时停止持久化，不退回明文。显式设置的 `MINIMAX_API_KEY` 优先且不会被脚本写入磁盘，状态中会标注 environment；这不等于本地加密保存。密钥不属于技能包、正文、配置样例或生成报告。

沙箱若阻止系统密钥库或网络，按执行工具规则申请对应操作权限，不将密钥改存明文。项目安装器为技能创建 `.venv` 并安装依赖；通过其他技能安装器只复制文件时，按配置教程补依赖。WebSocket MP3/FLAC 的分段合并需要用户本机 FFmpeg；PCM 可以只用 Python 标准库合并成 WAV。

结果保留完整原稿、送读稿、实际请求、脱敏响应、音频、原始字幕、SRT/VTT、追踪编号和官方使用量。WebSocket 另外保留事件记录、原始音频和各段文件，便于离线修复。

已发送但结果不明时，不自动重提交；先检查现有结果。`repair-websocket --out ...` 可从完整事件和原始流离线重建，无需再次付费。失败时保持实际状态，不擅自降级到 Turbo 或旧模型。
