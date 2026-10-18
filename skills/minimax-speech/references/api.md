# 调用与保存

核查和本机实测日期：2026-10-18。默认模型固定为 `speech-2.8-hd`，不自动切换模型或平台。

## 接口

| 操作 | 官方地址 |
| --- | --- |
| 同步完整文件 | `POST https://api.minimax.cn/v1/t2a_v2` |
| 标准 WebSocket | `wss://api.minimax.cn/ws/v1/t2a_v2` |
| 查询音色 | `POST https://api.minimax.cn/v1/get_voice` |

请求头 `Authorization: Bearer <key>`，HTTP JSON 请求另加 `Content-Type: application/json`。不需要额外 `GroupId`。脚本不允许自定义中转地址，拒绝将 API 鉴权头转发到重定向地址。

HTTP 使用 `stream=false`、`output_format=hex`。音频通过 `bytes.fromhex(data.audio)` 解码，不能按 Base64 解码。HTTP 状态和 `base_resp.status_code == 0` 都需要成功。

## 本机凭据

首次配置、注册、加密存储位置和故障处理见 [setup.md](setup.md)。所有平台使用 `python <skill>/run.py ...`，入口自动选择安装器准备的私有环境。全局参数 `--credential-file PATH` 仅适用于 Windows DPAPI，必须放在子命令之前。

## 任务 JSON

参见 [job.example.json](job.example.json)。

- `transport`：`http` 或 `websocket`。
- `text`：单段送读稿；`segments`：WebSocket 的有序文本列表，二者不能同时使用。
- `original_text`、`direction`：仅本地存档，不送入 API。
- `voice_id` 或 `voice_setting.voice_id`：真实可用的音色 ID。
- `text_normalization_mode`：HTTP 非流式 `basic/quality`；WebSocket 只能 `basic`。
- `audio_setting`：采样率、码率、格式、声道。默认 MP3、32000 Hz、128000 bps、单声道；HTTP 支持 mp3/flac/pcm/wav，本脚本 WS 支持 mp3/flac/pcm。
- `subtitle_enable`：默认 true；`subtitle_type` 默认 sentence，另可选 word，WS 可选 word_streaming。
- `pronunciation_dict`：`{"tone":["词语/读音"]}`。

每段文本小于10000字符；HTTP 官方建议超过3000字符考虑流式。脚本不自动切分长文并重复提交；先按语义规划分段、保持一致音色，并保存每段状态。

`--profile` 按给定顺序合并默认参数，任务 JSON 最后覆盖；词典跨 profile、`--dict` 和任务合并，不静默覆盖冲突词。profile 建议只存参数与词典，正文属于本次任务。

## WebSocket

```text
connected_success
-> task_start
-> task_started
-> task_continue(text)
-> task_continued(audio/subtitle)... is_final
-> 下一段 task_continue...
-> task_finish
-> 持续接收，直到 task_finished
```

`is_final` 是本次 `task_continue` 完成，不是整个连接完成。字幕可能在 `is_final` 之前到达，必须检查每条消息。`word_streaming` 同段会重复返回累计字幕，按该次输入与 `text_begin` 保留最新内容。

本机两段实测发现：每次 `task_continue` 的字幕时钟和文字位置重新从零开始。脚本保留分段原始字幕，用每段实际解码时长累加偏移，生成连续时间线；词级时间同步偏移。不要直接拼接每段 SRT。

本机实测 MP3 每段带独立元数据，直接拼接会出现不可靠的时长和中间 ID3。脚本保留原始流、每段文件，逐段解码合并成 `audio.master.wav`，再编码单个 MP3/FLAC。这样保留可靠 WAV 母版；派生 MP3 会有一次额外有损编码。

WebSocket PCM 使用标准库直接封装成 WAV，无需 FFmpeg。MP3/FLAC 需要 FFmpeg，生成前先检查，缺失时不发送收费请求。

```powershell
python <skill>/run.py configure-runtime --ffmpeg <absolute-path-to-ffmpeg>
python <skill>/run.py repair-websocket --out <existing-take-directory>
```

也可设置 `MINIMAX_FFMPEG` 或将 FFmpeg 放到 PATH。每台机器独立配置，仓库不附带个人路径或 FFmpeg。依赖清单为技能目录内的 `requirements.txt`；Windows 上 HTTP 与 DPAPI 仅用 Python 标准库。

## 结果与失败

- `job.json`：状态、模型、追踪编号、官方使用量、音频哈希、听感状态。
- `original.txt`、`spoken.txt`、`direction.txt`：原稿、送读稿、声音要求。
- `request.json`、`resolved-job.json`：实际请求和合并配置。
- HTTP：`response.json` 去掉音频大块和临时字幕链接；音频另存。
- `subtitles.raw.json`：官方原始字幕；WS 包含所属输入段；另存 `subtitles.timeline.json`。
- `subtitles.srt/vtt`：毫秒转时间码，不是改扩展名。
- WS：另有 `events.jsonl`、`stream.raw.*`、`segments/` 和 WAV 母版。

`extra_info.usage_characters` 是计费字符，不能用原文字数或 `word_count` 代替。`norm_text_char_count` 仅表示高质量归一化处理量；`usage_voice_count` 单独记录。WS 本次实测每个 final 对应本段使用量，脚本保留各段明细并求和；不据此编造人民币账单。

任务已发送后发生断线或超时，不自动重试。检查已保存结果和追踪编号；音频完成但字幕下载失败时会保留音频并标记警告，不重做配音。WS 后处理失败可离线修复；缺少 `task_finished` 时拒绝把未完成流标成成功。

当前脚本不实现 HTTP SSE、异步长文、音色创建、复刻或混音。需要这些功能时依据对应官方接口单独扩展，不能将当前实现误报为已覆盖。

## 官方依据

- [HTTP](https://platform.minimax.cn/docs/api-reference/speech-t2a-http)
- [WebSocket](https://platform.minimax.cn/docs/api-reference/speech-t2a-websocket)
- [调用指南](https://platform.minimax.cn/docs/guides/speech-t2a-websocket)
- [查询音色](https://platform.minimax.cn/docs/api-reference/voice-management-get)
- [HTTP OpenAPI](https://platform.minimax.cn/docs/api-reference/speech/t2a/api/openapi.json)
- [WebSocket AsyncAPI](https://platform.minimax.cn/docs/api-reference/speech/t2a/api/asyncapi.json)
