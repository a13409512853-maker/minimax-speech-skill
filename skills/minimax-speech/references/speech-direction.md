# 正文与声音要求

适用模型 `speech-2.8-hd`，核查日期 2026-10-18。

普通 TTS 的控制方式是音色、参数、正文组织、发音词典和少量行内标签；没有独立的自然语言 `prompt` 或 `instructions`。`direction` 只是本地记录，不会作为接口字段发送。

## 将要求转成执行参数

| 用户要求 | 执行动作 |
| --- | --- |
| 成熟、年轻、亲切、清亮、低沉 | 查询音色并选候选；先确定声音，再小幅调整其他参数 |
| 慢一点、快一点 | `voice_setting.speed`，0.5–2；通常从 0.95/1.05 小幅试起 |
| 大声、轻声 | `vol`，大于0且不超过10；不是分贝，不等价于情绪或耳语 |
| 音调低一点 | `voice_setting.pitch`，整数 -12–12 |
| 平静、开心、悲伤等 | 默认省略情绪，让模型根据内容判断；用户明确要求时设置下列兼容值 |
| 这里停半秒 | 在可发音文本之间插入 `<#0.5#>` |
| 这里轻笑 | 在指定位置加 `(chuckle)`；不能擅自全篇添加 |
| 地名、人名、术语有固定读法 | `pronunciation_dict.tone`；不确定读音时查证或询问，不编造 |
| 日期、金额、编号 | HTTP 非流式可用 `quality`；逐位数字/编号先按用户意图确定读法 |
| 亲切自然、不要广告腔 | 选合适音色并调整句式与节奏；没有 `advertising=false` 之类的参数 |
| 多角色轮流说话 | 按角色分开生成，再按时间线组合；不是 timbre_weights 混音 |

上述 0.95/1.05 是试听起点，不是官方保证效果的预设。情绪、感染力、音色适配和自然度需要听感确认。

2.8 保守情绪列表：

```text
happy sad angry fearful disgusted surprised calm
```

不发送 `whisper`；当前文档说明 2.8 不支持。`fluent` 的说明限定 2.6，不把它当作已确认的 2.8 能力。想要“温柔”“小声”时优先选音色，不能用不兼容的耳语参数替代。

## 停顿与非语言声音

`<#x#>` 单位为秒，0.01–99.99，最多两位小数；不能放首尾、不能连续堆叠，需要在可发音正文之间。

同步接口明确列出以下19种标签：

```text
(laughs) (chuckle) (coughs) (clear-throat) (groans)
(breath) (pant) (inhale) (exhale) (gasps)
(sniffs) (sighs) (snorts) (burps) (lip-smacking)
(humming) (hissing) (emm) (sneezes)
```

```text
太好了！(chuckle)我们终于完成了。
欢迎回来。<#0.35#>我们开始今天的分享。
```

标签表示声音事件，不是持续情绪指令。不要把 `[温柔地]`、`[停顿]`、SSML 或自造 `<emotion>` 标签当作已支持语法。英文圆括号小写词会被脚本视作可能的标签，未知内容会要求移除或改用普通正文。

## 发音与忠实度

```json
{"tone": ["重庆/(chong2)(qing4)"]}
```

可通过多个 `--dict` 合并全局、项目和任务词典。脚本去重，并拒绝同词不同读法的冲突，避免静默覆盖。预览必须看到词典实际进入请求。

原稿存 `original_text`，送读稿存 `text` 或 `segments`。除非用户允许润色，不为追求“自然”增删实词、改数字含义或扩写缩略词。元指令放 `direction`，不能变成朗读内容。字幕原始文件保留控制标签，导出的 SRT/VTT 移除已确认的声音标签和停顿符。

## 音色设计分支

仅在用户需要新音色时另行使用官方 `/v1/voice_design`。这是另一项外部操作，当前脚本没有实现；普通配音流程不默认调用。

可参考的描述结构：语言/口音、声音年龄感、音色质感、表达方式、使用场景。示例：

> 标准普通话，成年女声，温暖亲切，咬字清晰，语气克制，适合知识讲解，节奏自然。

这是根据官方示例归纳的写作方法，不是 API 固定模板。`preview_text` 最多500字符，生成的 `voice_id` 再用于正式 TTS；该接口本身不接收 `speech-2.8-hd` 模型选择字段。

## 官方依据

- [同步 HTTP 参数与标签](https://platform.minimax.cn/docs/api-reference/speech-t2a-http)
- [同步 WebSocket 参数](https://platform.minimax.cn/docs/api-reference/speech-t2a-websocket)
- [官方 TTS Guide](https://github.com/MiniMax-AI/skills/blob/main/skills/frontend-dev/references/minimax-tts-guide.md)
- [Speech 2.8 发布说明与标签示例](https://www.minimax.io/news/minimax-speech-28)
- [音色设计](https://platform.minimax.cn/docs/api-reference/voice-design-design)
