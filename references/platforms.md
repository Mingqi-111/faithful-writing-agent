# 宿主接入与持久化

官方资料核实于 2026-10-18。下面区分“文档说明支持”与“本包已经实测”。本包不用自己的模型 API，不安装 MCP 服务，不开网页；推理和工具权限来自宿主，仍消耗宿主账号额度。

## Codex

将整个 `faithful-writing-agent` 文件夹放入当前写作项目的 `.agents/skills/`。包内安装脚本可由 Codex 执行：

```bash
python3 /技能包实际路径/scripts/install.py --host codex --project /写作项目实际路径
```

也可以先在聊天中直接指定包内 SKILL.md，要求依其流程改稿；这次显式使用不等于已安装到所有新任务。官方支持 Skill 携带 scripts/references，并支持隐式匹配与显式选择。安装后在同一写作项目发文章即可；CLI/IDE 可以用 `$faithful-writing-agent`，桌面界面按其技能选择器使用。使用应用已有模型权限，不需要新配 API。[官方说明](https://learn.chatgpt.com/docs/build-skills)

默认状态随当前写作目录保存；新建不同目录不会自动共享记忆。需要全局安装时由用户明确选择其个人技能位置，不由本包偷偷修改全局配置。

## Claude Code

项目安装到 `.claude/skills/faithful-writing-agent/`，或让 Claude Code 执行本包安装脚本 `--host claude-code --project /实际项目路径`。在该项目使用技能即可。已有相应订阅的用户可以登录 Claude 账号使用 Code，不要求额外 API Key。[技能路径](https://code.claude.com/docs/en/skills)、[账号与订阅](https://support.claude.com/en/articles/11145838-use-claude-code-with-your-pro-or-max-plan)

官方当前支持从 Claude 账号向新版 Code 同步已启用技能；同步目录不可作为反馈数据库。状态放在独立工作目录，避免技能更新覆盖；本机文件也不会因此自动跨设备同步。[同步说明](https://code.claude.com/docs/en/skills#skills-synced-from-claude-ai)

## Claude.ai / Desktop 的普通聊天

在 Customize → Skills → `+` → Create skill → Upload a skill 导入本包 ZIP 并启用；同时需要代码执行能力。ZIP 内只有一个顶层同名文件夹，包含 SKILL.md 与脚本。平台支持携带 Python/JS 脚本。[使用 Skill](https://support.claude.com/en/articles/12512180-use-skills-in-claude)、[创建要求](https://support.claude.com/en/articles/12512198-how-to-create-custom-skills)

可以在当前会话改写、执行检查及评测，但不要默认临时沙箱的 SQLite 文件能跨聊天保留。自动聊天记忆可以概括偏好，不足以代替精确的反馈 ID、版本和评测账本。[聊天记忆](https://support.claude.com/en/articles/11817273-use-claude-s-chat-search-and-memory-to-build-on-previous-context)

当前包的可移植状态是 `.faithful-writing-agent/state.sqlite3`（最终以脚本返回的 state_path 为准）。临时沙箱中，宿主需在脚本退出后把状态文件作为可下载附件交给用户；下一会话需重新提供该文件并放回同一状态目录。只恢复用户自己可信的文件。这个恢复过程不能宣传成“全自动跨会话学习”；要满足完全无感长期记忆，应选持久工作目录或另做平台原生存储适配。

## WorkBuddy

桌面端：专家·技能·连接器 → 技能 → 添加技能 → 上传技能，导入本地技能包。官方说明 Skill 可携带脚本并执行文件操作。[官方技能说明](https://www.codebuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Skills-Market)

项目模式还支持 `.codebuddy/skills/<name>/SKILL.md`。可由宿主执行本包安装脚本 `--host workbuddy --project /实际项目路径`。这是 WorkBuddy 自身的官方路径；本包不假定存在 `~/.workbuddy/skills`。[项目说明](https://www.codebuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Project)

反馈写入固定的个人写作目录。WorkBuddy 自带记忆会整理和概括，不能当作原样保留的 benchmark 数据库。[记忆说明](https://www.codebuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Memory)

## 扣子 / Coze

优先选择扣子桌面端的本地技能接入：设置 → 允许访问本地文件 → 本机技能扫描的管理目录 → 添加包含 SKILL.md 的技能文件夹；然后在对话 `+ → 技能 → 从个人设备添加技能`。云端 Agent 读取该技能，个人电脑和桌面端需在线。[官方使用说明](https://docs.coze.cn/cozespace_using_skills)

另一条路径是在扣子编程上传 `.skill` 或 `.ZIP`，经平台解析与重新打包后部署到扣子对话；上传源码包并不等于原样部署成功。本次只交付导入包，不替用户创建、发布或部署技能。[开发技能](https://docs.coze.cn/guides_vibe_coding_skill)、[部署说明](https://docs.coze.cn/guides_deploy_skill)

扣子云盘可作为 Agent 工作目录，生成文件可保存；共享项目文件对成员可见，个人偏好应使用个人目录。[云盘说明](https://docs.coze.cn/cozespace_cloud_drive)

脚本需先确认该工作目录可用、Python/sqlite3 可执行，再使用固定 `--data-dir`。官方持久云盘不等于已经验证本包 SQLite 的跨会话读写：必须保存后在下一会话重新读取验证，不能在未完成时声称记忆已持续。

“扣子编程内编程助手的技能”“扣子对话技能”和开源 Coze Studio 是不同入口；本包不声称开源 Studio 能直接导入同一 ZIP。

## 能力降级规则

| 实际能力 | 可提供的行为 |
|---|---|
| 模型 + Python/文件执行 + 持久目录 | 改写、检查、记录、benchmark、候选验证和版本回退 |
| 模型 + Python/文件执行 + 临时目录 | 当前会话完整流程；跨会话状态需导出/恢复 |
| 模型可读 Skill，但不能执行脚本 | 规则辅助改写和自审；不能宣称执行了脚本检查或可靠的版本评测 |
| 无独立审校上下文 | 标记 self_review；不能偷偷写成 independent 或自动降低启用门槛 |

先使用宿主已有的代码环境；若 Codex 暴露了内置依赖运行时查询工具，可用其返回的 Python 路径。不要为了初次改稿要求用户配置模型 API。应用/组织可能限制技能、代码或文件权限，这些权限不能由 Skill 自己创造。
