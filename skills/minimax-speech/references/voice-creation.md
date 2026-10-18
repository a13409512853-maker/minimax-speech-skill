# 音色设计与参考音频复刻

核对日期：2026-10-19。使用同一套官方 API Key 和 OS 加密存储；无需再次配置密钥。以下命令通过技能 `run.py` 执行。

## 选择方式

| 需求 | 命令 | 输入 | 结果 |
| --- | --- | --- | --- |
| 根据文字描述创造声音 | `voice-design` | `prompt`、`preview_text` | 音色ID、hex试听音频 |
| 复刻有权使用的参考声音 | `voice-clone` | 本地音频或已上传文件ID、自定义音色ID | 音色ID，可选试听链接 |
| 调整已有声音的表现 | `generate --profile ...` | 配音任务、语速/音高/情绪等 | 配音与字幕 |

这两种创建操作会在官方平台创建音色。音色设计必须合成试听；复刻中的 `text` 会触发试听合成和对应费用。复刻音色的后续使用也可能产生音色相关费用，以平台当期说明为准。不要把安装、预览或接口开发当作收费创建授权。

## 文字设计

从 [voice-design.example.json](voice-design.example.json) 复制任务：

```text
python <skill>/run.py voice-design --job design.json --dry-run
python <skill>/run.py voice-design --job design.json --out voices/design-01
```

`prompt` 描述声音，`preview_text` 是实际朗读的台词，1–500字符。可选 `voice_id` 自定义ID，不提供则由官方生成；中国站还支持布尔字段 `aigc_watermark`。接口没有 `model`、`voice_setting` 或通用 `instructions`，不要加进去。

建议先确定语言/口音、声音年龄感、音域和质感、表达习惯与场景；避免相互冲突的要求。角色设定图只能用于设计方向，不能据此宣称还原了原本不存在的真实声音。例如：

> 标准普通话，年轻成年女声，音色清亮、干净，带自然的笑意。像热情的大学同学，表达灵动但不尖细，咬字清晰，适合校园角色对白。

这是根据官方示例归纳的提示写法，并非官方固定模板或效果保证。需要多方案时分别提交明确授权的数量，保留每版描述与音色ID；比较阶段尽量使用同一段试听台词。

## 参考音频复刻

调用前需完成官方个人或企业认证。只使用用户拥有声音使用权、且授权上传和复刻的素材；不替用户编造授权。

从 [voice-clone.example.json](voice-clone.example.json) 复制任务，填写音频路径、音色ID，并在获得实际授权后将 `authorized` 改为 `true`：

```text
python <skill>/run.py voice-clone --job clone.json --dry-run
python <skill>/run.py voice-clone --job clone.json --out voices/clone-01
```

- 主参考 `audio_path`：MP3/M4A/WAV，10–300秒，每文件不超过20MB。脚本通过 `purpose=voice_clone` 上传到 `/v1/files/upload`，再将返回的整数 `file_id` 送入 `/v1/voice_clone`。
- 也可用已上传的整数 `file_id` 代替 `audio_path`。此时本机无法重新核查远端音频，请用户自行确认规格和授权。
- `voice_id`：8–256位，英文开头，仅含英文字母、数字、`-`、`_`，不能以 `-` 或 `_` 结尾，且不能重复已有ID。
- `clone_prompt` 可选。若提供，需同时有短示例音频和逐字对应文本，文本末尾须有标点。其 `audio_path` 必须短于8秒，同样不超过20MB，以 `purpose=prompt_audio` 上传；或用 `prompt_audio` 填写既有整数文件ID。
- `text` 可选，1–1000字符，用于复刻试听；提供后脚本发送 `model=speech-2.8-hd`。不提供时只创建音色，不自动合成试听。
- `need_noise_reduction`、`need_volume_normalization`、`aigc_watermark` 为可选布尔值，不自动改动参考录音。
- `text_validation` 可选，最多200字符，用于官方 ASR 文本校验；`accuracy` 配合使用，0–1，官方说明传0时按默认0.7处理。不要与新配音的 `text` 混淆。
- `language_boost` 可选，遵循官方枚举，例如 `Chinese`、`Chinese,Yue`、`auto`。

可选短示例写法：

```json
{
  "clone_prompt": {
    "audio_path": "reference/prompt.wav",
    "prompt_text": "这段文字与示例录音完全一致。"
  }
}
```

相对路径以任务 JSON 文件夹为基准。PCM WAV 只需 Python 标准库；MP3/M4A 用 FFprobe 检查时长，可将其加入 PATH、设置 `MINIMAX_FFPROBE`，或配置与 FFprobe 同目录的 FFmpeg：

```text
python <skill>/run.py configure-runtime --ffmpeg /path/to/ffmpeg
```

官方复刻文档 `file_id` 描述中有一句将子属性与主参考混写，但 schema 将 `clone_prompt` 列为可选；实现依照 schema，短示例一旦提供就同时要求音频和文本。没有补传示例时，不自行生成或上传虚假的示例素材。

## 结果与复用

每次创建必须使用新输出目录：

- `voice.json`：音色ID、来源与创建日期。
- `profile.json`：可直接复用的 TTS 音色参数。
- `request.json`、`resolved-job.json`、`response.json`、`job.json`：请求、任务状态和脱敏响应；音频大块与临时签名链接不写入响应归档。
- `preview.*`：设计试听或复刻试听。根据实际文件头辨认扩展名；不能辨认时保留为 `.bin` 并报出警告。未进行人工听审时标记 `listening_review=pending`。
- `upload-voice_clone.json`、`upload-prompt_audio.json`：本次上传结果；`job.json` 保存已确认文件ID、时长和哈希，不复制原始录音。

正式配音任务中省略旧的 `voice_id`，避免任务覆盖 profile 中的新音色：

```text
python <skill>/run.py preview --job narration.json --profile voices/design-01/profile.json
python <skill>/run.py generate --job narration.json --profile voices/design-01/profile.json --out takes/take-01
```

后续可在任务 `voice_setting` 中微调 `speed`、`pitch`、`vol`、`emotion`，也可换台词和发音词典；这改变表达，不是在本机训练模型。修改设计描述应作为新一版音色创建。

官方说明：复刻音色若7天内未正式调用，会被删除。创建试听不能当作已经完成正式 TTS 调用，不自动发起保活音频。使用 `voices --type voice_cloning` 或 `voices --type voice_generation` 查询相应类型。

上传超时或创建结果不明时不自动重试；先看已有上传响应与任务状态，已取得的文件ID可填入新任务复用。创建成功但试听下载失败会保留 `profile.json` 并标记警告，不应重新创建音色。复刻试听从 HTTPS 结果链接下载，不携带 API 鉴权头。

## 官方依据

- [音色设计](https://platform.minimax.cn/docs/api-reference/voice-design-design)
- [音色快速复刻](https://platform.minimax.cn/docs/api-reference/voice-cloning-clone)
- [文件上传](https://platform.minimax.cn/docs/api-reference/file-management-upload)
- [上传主参考](https://platform.minimax.cn/docs/api-reference/voice-cloning-uploadcloneaudio)
- [上传短示例](https://platform.minimax.cn/docs/api-reference/voice-cloning-uploadprompt)
