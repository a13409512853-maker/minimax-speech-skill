# 注册与本地配置

核实日期：2026-10-18。安装包不提供任何共享密钥。每位使用者配置自己的 MiniMax 官方密钥，费用由对应账号承担。

## 没有账号

1. 打开 [MiniMax 官方注册/登录页](https://platform.minimax.cn/login?source=platform_docs)，按页面要求完成注册和登录。
2. 进入 [接口密钥](https://platform.minimax.cn/user-center/basic-information/interface-key)，选择“创建新的 API Key”。这里使用官方**按量付费 API Key**。
3. 在 [账户余额](https://platform.minimax.cn/user-center/payment/balance) 查看语音调用可用资源，按需充值；不要假设网页语音产品的订阅等于开放平台 API 余额。
4. 复制新密钥，回到本机隐藏输入窗口完成下一节配置。不要上传仓库或贴入 Issue。

官方图文来源：[前置准备](https://platform.minimaxi.com/docs/guides/quickstart-preparation)。页面会变化，以官方当前要求为准。遇到权限或额度问题时结合 [错误码](https://platform.minimax.cn/docs/api-reference/errorcode) 排查，不用反复生成试听判断。

## 已有密钥

将 `<skill>` 替换为安装结果显示的技能目录：

```text
python <skill>/run.py configure
python <skill>/run.py credential-status --json
```

第一条命令会隐藏输入，保存后验证本机可解密；不会联网，不证明密钥已通过官方鉴权。已有保存值时默认拒绝覆盖，确需更换用 `configure --replace`。

AI 应在安装完成后主动提示你配置。推荐在它打开的本机终端中输入，密钥无需经过聊天。若 AI 没有打开终端的能力，可自行运行上述命令。`configure --stdin` 仅供可信程序通过管道传入；不使用包含密钥的 `echo`、命令参数或临时文件。它要求管道结束输入才会保存。对话中提供过的密钥仍可能存在于聊天记录中，本地加密不会删除聊天记录。

## 存储与删除

| 系统 | 保存方式 | 前提 |
| --- | --- | --- |
| Windows | 当前用户 DPAPI，加密文件 `%LOCALAPPDATA%/MiniMaxSpeech/credentials.dpapi` | 同一 Windows 用户上下文，可访问 DPAPI |
| macOS | 系统 Keychain，服务 `minimax-speech`、账户 `official-api-key` | 已安装 keyring，钥匙串解锁；系统可能询问访问许可 |
| Linux | Secret Service，同名服务与账户 | 已安装 keyring，用户 D-Bus 会话与已解锁的系统密钥库 |

只实例化指定系统后端，不使用 keyring 的自动 fallback，不存明文 JSON 或 `.env`。Linux 无桌面会话/密钥库时会报 unavailable；需准备 Secret Service 或显式使用下述临时环境变量，不假装已加密保存。锁定的密钥库应先解锁，不能当作 missing 覆盖。

`MINIMAX_API_KEY` 为主动设置的临时/CI 覆盖方式，优先于本机保存值；本项目不负责该变量的加密，不将其持久化。正常桌面使用推荐 `configure`。

```text
python <skill>/run.py forget-credential
```

此命令只删除本技能保存的本机凭据，不清除外部设置的环境变量，不吊销官方密钥。环境变量存在时结果会明确提示。要吊销密钥请到官方接口密钥页面删除。系统加密不能阻止已获同一用户权限的恶意程序读取密钥。

## 依赖与安装目录

需要 Python 3.10+。仓库 `install.py` 默认安装到 `~/.agents/skills/minimax-speech`（Codex）；`--agent claude` 使用 `~/.claude/skills/minimax-speech`；`--dest PATH` 指定其他工具的 **skills 父目录**。安装器创建技能私有 `.venv`，不修改系统 Python 包。Linux 若缺少 venv/ensurepip，先按本机发行版方式安装对应 Python venv 包。

若其他技能安装器仅复制技能文件，在已安装目录补依赖：

```text
python -m venv <skill>/.venv
# Windows:
<skill>/.venv/Scripts/python.exe -m pip install -r <skill>/requirements.txt
# macOS / Linux:
<skill>/.venv/bin/python -m pip install -r <skill>/requirements.txt
python <skill>/run.py onboard
```

含空格路径要按当前终端语法加引号。Windows 的 HTTP 与 DPAPI 不依赖第三方包，`--no-deps` 可用于离线安装；WebSocket 需要 websockets，macOS/Linux 加密保存需要 keyring 与系统服务。运行时目录不能跨机器复制，应在目标机器重建 `.venv`。

WebSocket 输出 MP3/FLAC 还需自行安装 FFmpeg，加入 PATH 或配置：

```text
python <skill>/run.py configure-runtime --ffmpeg <absolute-path>
```

HTTP 输出不需要 FFmpeg；WebSocket PCM 可直接生成 WAV 母版。运行配置存于 Windows LocalAppData 或其他系统的 `~/.config/minimax-speech/runtime.json`，不会写进仓库。

## 状态与后续使用

`onboard --json` 和 `credential-status --json`：ready 退出0、missing 退出2、unavailable 退出3；均不调用 API。keychain 访问可能触发系统解锁提示。AI 必须区分这些状态。

安装不生成音频。你提出配音/测试要求后，AI 应先预览正文、音色与参数再生成；模型为 `speech-2.8-hd`。请求结果未知时不自动重试。声音控制方法见 [speech-direction.md](speech-direction.md)，接口与结果文件见 [api.md](api.md)。
