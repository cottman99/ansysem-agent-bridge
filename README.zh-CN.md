<p align="center">
  <a href="README.md">English</a> · <strong>简体中文</strong>
</p>

# AnsysEM Agent Bridge

<p align="center">
  <img src="docs/assets/readme/logo.png" width="150" alt="AnsysEM Agent Bridge logo">
</p>

<p align="center"><strong>让 Agent 检查和修改你真正指定的 AEDT 设计，而不是把原工程当作草稿。</strong></p>

![受保护的电磁封装在独立副本上修改，并经过全新重开验收](docs/assets/readme/ansysem-user-value-v2.png)

AnsysEM Agent Bridge 是一个非官方、本地优先的 Ansys Electronics Desktop
桥接工具。它帮助 Codex、Pi Agent 等通用 Agent 精确识别项目与设计，
检查 HFSS 3D Layout 实时状态，在非覆盖副本上进行受控修改，并返回
带证据的产物。

Bridge 把 AEDT 知识和原生 API 行为留在 EDA 主机。重复的本机或 SSH
工作统一经过
[EDA Bridge Runtime](https://github.com/cottman99/eda-bridge-runtime)，
因此长任务、重试、耗时和审计只有一条路径。

> [!IMPORTANT]
> 本项目仍是公开 Alpha，与 Ansys, Inc. 无隶属或背书关系。首次使用请
> 从可丢弃工程开始，并先查看能力边界。

## 从一个明确的 AEDT 安装开始

在 AEDT 主机安装：

```console
pipx install ansysem-agent-bridge
ansysem-agent --pretty doctor
```

本包会自动安装兼容的 `eda-bridge-runtime` Python 依赖，用户不需要
手工再装第二个 Python 包。如果 Agent 在另一台电脑上运行，只需在
Agent 主机启用 Runtime MCP/插件；只运行 AEDT 的主机不需要 Agent 侧插件。

明确配置一套 AEDT，不静默选择最新版本：

```console
ansysem-agent --pretty setup \
  --aedt-root /path/to/AnsysEM/v261 \
  --version 2026.1 \
  --docs-root /path/to/private/local/docs
```

实时工作需要管理员一次性把匹配的 Python、Display 和模块环境固定到
命名的 [Runtime Profile](docs/EXECUTION_CONTEXT_CONTRACT.md)。之后工程师
只需在 AEDT 选择项目/设计，或粘贴插件复制的 Context，再用自然语言
说明任务。

## 你可以怎样对 Agent 说

| 自然语言任务 | Bridge 会检查什么 |
| --- | --- |
| “我现在使用的是哪套 AEDT、哪个设计？” | 核对版本、项目、设计、编辑器、进程、主机、Display 和 Profile 身份。 |
| “修改前先检查这个工程。” | 验证完整工程 Bundle，并返回受控的对象、端口、Setup 和版本事实。 |
| “查一下这个版本完成该操作的正确 API。” | 查询私有本地文档并返回聚焦证据，不启动或修改 AEDT。 |
| “导出这个版图的顶视图。” | 使用原生编辑器导出，并明确图片能证明和不能证明的内容。 |
| “按这些确定规则修改版图或金线。” | 在副本上执行类型化操作，保存关闭、全新重开并逐项断言。 |
| “继续调整候选版本，不要再建客户版本。” | 复用一个候选工作区，支持检查点、回滚和幂等 Patch。 |
| “现在把通过检查的候选版本交付。” | 从冻结源重放，最终新会话验证后只提交一个不可变输出。 |
| “连接断了，AEDT 任务到底完成没有？” | 读取持久化回执和事件，不重新执行任务。 |

完整支持范围和停止规则见[能力矩阵](docs/CAPABILITY_MATRIX.md)。

## 更安全的模型修改流程

1. 选择或复制精确的 AEDT 项目/设计 Context。
2. 检查实时身份和源 Bundle。
3. 从冻结源创建一个任务候选工作区。
4. 把同一次观察得到的兼容修改合并成类型化 Patch。
5. 每轮保存关闭并全新重开后，才接受检查点。
6. 只有用户要求交付时，才正式 Promotion 一次。

这同时避免了直接修改原工程的风险，也避免每个小修正都创建永久版本。

完全确定的一次性修改可使用：

```console
ansysem-agent --pretty --profile <profile-id> \
  model apply --plan /path/to/operation-plan.json --redact-paths
```

迭代任务使用[候选工作区生命周期](docs/WORKSPACE_LIFECYCLE.md)。客户对象名、
坐标和值只进入项目自己的计划，不进入公开 Bridge、Skill 或测试。

## 用证据，而不是截图代替证明

维护中的真实主机验收覆盖 Linux 上的 AEDT 2026 R1，包括安装/Display
身份、工程创建与检查、持久化任务、非覆盖工作区、全新重开、类型化断言
和产物哈希。见
[脱敏 AEDT 2026 R1 验收](docs/VALIDATION_AEDT_2026R1_LINUX.md)。

原生版图导出只能证明 AEDT 导出了指定实时编辑器状态。可见对象或截图
不能证明电气正确、网格、收敛或求解完成；求解结论必须有独立求解证据。

## AEDT Context 插件

轻量 Automation-tab 插件提供：

- **Use Current Design with Agent**
- **Copy Agent Context**
- **Agent Connection Status**

复制的 Context 包含无秘密的本机定位符、软件身份、Display、设计目标、
新鲜度和能力提示。精确私有路径保留在 AEDT 主机。Context 只选择目标，
不授权修改或求解。

精确身份模型见[执行上下文契约](docs/EXECUTION_CONTEXT_CONTRACT.md)。

## 本机与远程使用同一条路径

AEDT 主机上的重复操作使用：

```console
ansysem-agent runtime serve
```

Runtime 复用本机或 SSH 通道，记录每次简短动机和阶段耗时，并在 AEDT
工作前持久化长任务回执。工程、文档和产物默认留在 EDA 主机。Agent 与
AEDT 同机时也注册本机连接并经过 Runtime，从而保持相同的重试、审计和
证据行为。

## 安全边界

- 不静默选择最新版本，不猜前台窗口；
- HFSS 3D Layout 需要完整 Bundle 时，不凭单个 `.aedt` 文件宣称完整；
- 默认公开接口不允许任意 Python；
- 不覆盖源工程，全新重开前不接受修改成功；
- 候选尝试不创建永久交付版本；
- 不使用盲目 GUI 坐标，不以截图代替成功；
- 不强杀 AEDT，不静默丢弃修改；
- 不把文档、可见对象或图片导出当作求解证据；
- 公开仓库不包含客户工程、私有路径或厂商文档。

## 更多信息

- [能力与证据矩阵](docs/CAPABILITY_MATRIX.md)
- [候选工作区生命周期](docs/WORKSPACE_LIFECYCLE.md)
- [执行上下文契约](docs/EXECUTION_CONTEXT_CONTRACT.md)
- [架构](docs/ARCHITECTURE.md)
- [版本契约](docs/RELEASE_CONTRACT.md)
- [安全策略](SECURITY.md)
- [脱敏 Linux 验收](docs/VALIDATION_AEDT_2026R1_LINUX.md)
