# MiniMax Speech Skill Repository

本仓库用于安装和维护 `skills/minimax-speech`。只有用户请求安装或更新时执行安装；仅浏览仓库不构成安装授权。

## 用户要求安装时

1. 读取 README.md 与技能 SKILL.md；使用 Python 3.10+。
2. 获取完整仓库后运行 `python install.py --non-interactive --json`。根据用户正在使用的工具选择 `--agent` 或 `--dest`。Codex 默认 `~/.agents/skills`；不要同时复制多份造成发现冲突。
3. 安装失败时处理具体依赖/权限问题，不将失败误报为成功。安装器不覆盖不同的已有文件，更新前保留用户修改并检查差异。
4. 检查输出 `credential.status`：ready 则无需再索取；missing 则**主动询问用户是否已准备好自己的官方按量付费 API Key**，同步提供官方注册、密钥页面与安装后的 `references/setup.md`；unavailable 则先修复系统密钥库，不用新密钥覆盖未知状态。
5. 优先打开用户可操作的本机终端运行 `python <skill>/run.py configure`，隐藏收取并加密保存。用户在对话中提供密钥时，仅使用工具明确支持的保密输入或可信进程 stdin；不把值插入 shell 命令、参数、脚本、临时文件、日志或回答。没有保密传递能力时引导本机隐藏输入。
6. 运行 `python <skill>/run.py credential-status --json` 验证本地可读性，准确说明配置状态。安装请求本身不授权生成付费试听；有明确测试/生成请求才执行。

不要止步于“已安装”：缺凭据时完成主动引导；用户尚未提供时标记“等待用户配置”，不能伪报配置完成。不要设置后台任务来追问，也不要替用户注册、充值或保存网页登录密码。

## 维护时

保留官方模型与固定端点。常规 TTS 不添加虚构 prompt 字段。凭据只使用指定 OS 加密后端，禁止明文 fallback；保留 unknown-result 不自动重试行为。测试不得调用收费 API。

修改后运行 unittest 与 `tools/check_release.py`。源码不包含 `.venv`、真实凭据、用户生成结果或账号资料。API 返回字段变化时先核对官方文档；不要靠增加收费重试掩盖问题。
