# Codex Auto Archive

[English](../README.md) · **简体中文** · [日本語](README.ja.md) · [Español](README.es.md)

通过 Codex 对话管理它自身的 **Archive**：闲置归档、任务完成、PR/CI 条件、白名单、批量预览、恢复与本地定时检查。后台不调用模型，不删除会话，不直接编辑 Codex 数据库或会话文件。

**当前边界：** 本机 Codex 0.160.0 的独立 App Server 无法可靠看到 Desktop/其他进程的执行状态，也没有置顶字段。插件默认跳过这些会话，并保持 Dry Run。因此 v0.1.0 不能宣称已实现本机 Desktop 的无条件全自动归档。原生归档/恢复、规则引擎和 MCP 均有测试；详细情况见[兼容性与验证](COMPATIBILITY.md)。

## 安装

准备 Python 3.11+、[uv](https://docs.astral.sh/uv/getting-started/installation/) 和支持 App Server/Plugin 的 Codex CLI。PR/CI 规则可选用已登录的 GitHub CLI，不再索取 Token。

```bash
git clone https://github.com/Jineggegg/codex-auto-archive.git
cd codex-auto-archive
bash scripts/install.sh
```

Windows PowerShell：

```powershell
git clone https://github.com/Jineggegg/codex-auto-archive.git
cd codex-auto-archive
powershell -ExecutionPolicy Bypass -File scripts/install.ps1
```

安装器注册官方本地插件和系统定时器；首次只预览。打开新 Codex 会话后，在 `/hooks` 或原生审核界面信任本插件的命令钩子。官方要求用户审核，安装器不会绕过。未启用钩子时仍可检查时间规则。

Windows 与 WSL 的 `CODEX_HOME` 分开管理。WSL 安装不会改 Windows Desktop。PowerShell 安装器支持 `-CodexHome`；Linux 可先设置 `CODEX_HOME`。定时器使用期间保留项目和运行环境。

## 直接说

- “以后闲置 7 天自动归档，关联 PR 合并后立即归档。”
- “关闭任务完成自动归档，但保留时间归档。”
- “当前项目使用 14 天归档规则。”
- “把当前会话加入白名单。”
- “这个项目永远不要自动归档。”
- “预览未来 7 天会归档的会话。”
- “查最近自动归档的 10 个会话。”
- “恢复昨天自动归档的对话。”
- “切换为标准模式。”“语言设为中文。”

只有明确说“开启自动归档”才退出 Dry Run。修改天数、安装或切换预设不会擅自开启真实执行。开启后仍须通过运行状态、置顶、Goal 和子会话等检查，未知就跳过。

手动归档/恢复先展示预览，再由你确认。当前会话使用宿主提供的准确 Thread ID；拿不到时要求选择，不猜。归档当前会话至少延迟 60 秒并等待空闲，新输入会取消。返回“已调度”不代表“已归档”。

## 默认配置

时间归档 30 天；任务完成、PR Merged、PR Closed、CI Success、Issue Closed、Goal Completed 和用户明确完成各自关闭；完成宽限 30 分钟；保护置顶；恢复后冷却 7 天；每 60 分钟扫描；每次最多归档 20 个会话（含后代）；Dry Run 开启。

各触发器独立。优先级：白名单 > 安全条件 > 会话覆盖 > 项目覆盖 > 全局 > 默认。`workflow_all_of` 可要求 PR 合并和 CI 成功同时成立；单次回复结束、Stop 或 SessionEnd 都不算任务完成。

保守模式：90 天/24 小时宽限；标准：30 天/30 分钟；积极：7 天/5 分钟。预设关闭完成和工作流触发，保留置顶保护；项目/会话覆盖不被抹掉。语言选项为自动、英文、中文、日文、西班牙文，MCP 机器字段保持英文。

[维护与卸载](../README.md#tools-and-maintenance) · [工具接口](TOOLS.md) · [安全与架构](ARCHITECTURE.md)
