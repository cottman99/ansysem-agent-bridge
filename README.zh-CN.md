<p align="center">
  <a href="README.md">English</a> · <strong>简体中文</strong>
</p>

# AnsysEM Agent Bridge

<p align="center">
  <img src="docs/assets/readme/logo.png" width="150" alt="AnsysEM Agent Bridge logo">
</p>

<p align="center"><strong>从叠层、几何和端口到求解后的原生 Report，同时不把原工程当作草稿。</strong></p>

![射频工程师从衬底叠层和端口出发，经过电磁求解得到 S 参数结果](docs/assets/readme/ansysem-engineer-workflow-v3.png)

## 一段对话完成 HFSS 3D Layout 建模到报告

> “从空白工程开始，建立这个叠层和走线，放置两个边缘端口，求解1–5 GHz，
> 导出 S11/S21，并把结果图留在 AEDT 里。”

| 在 AEDT 中建立并重开的模型 | 留在工程中的原生结果 |
| --- | --- |
| ![真实 AEDT 窗口中的工程树、TOP SUB GND 叠层、走线和边缘端口](docs/assets/readme/ansys-native-layout-stackup.png) | ![公开双端口验收工程中的原生 AEDT S 参数 Report](docs/assets/readme/ansys-native-s-parameters.png) |

公开的 AEDT 2026 R1 验收完整执行了这条路径：

- 创建空白 HFSS 3D Layout 工程；
- 添加两种材料和 GND / SUB / TOP 叠层；
- 创建地平面、信号走线、P1 / P2 和 Setup1；
- 求解1–5 GHz的5个明确频点；
- 将有限 S 参数数据导出为 CSV，并持久保存原生 Report；
- 保存关闭，并在全新重开后通过验收。

两张图都是真实 AEDT 应用窗口。模型视图是在验收结束后，使用同一公开类型化
构建合同独立回放并截图，不计入测试耗时；结果图来自已经求解并持久保存的原生
AEDT Report。

AnsysEM Agent Bridge 把 Codex 或 Pi Agent 连接到一个明确的 AEDT 工程和
Design。它能检查已有工程，建立维护中的叠层/几何/端口，求解明确扫频，并在
受保护候选版本上执行已知版图或金线修改。本机与 SSH 工作都经过
[EDA Bridge Runtime](https://github.com/cottman99/eda-bridge-runtime)，
因此长任务、重试、耗时和审计使用同一条路径。

新增 PyAEDT 用法不需要再为每个方法增加 Bridge wrapper。Agent 结合版本匹配
的官方文档和随包提供的小型启动经验库，通过带源指纹、超时、staging、全新
重开和验收的通用事务执行官方代码。已有 build、solve、model 操作作为与经验
资产绑定的编译快捷方式保留，用于省 token 和降低转写错误，而不限制官方 API
的更广覆盖。

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
| “从空白工程开始：建立这个叠层和走线，放两个边缘端口，并添加 1–5 GHz 设置。” | 使用类型化材料/叠层/几何/端口计划，保护空白源工程，并要求 PyEDB 与 AEDT 全新重开读回。 |
| “跑这五个频点，把 S11/S21 导出为 CSV，并在 AEDT 里把 S 参数图搭好。” | 创建明确命名的离散扫频，等待求解，检查每一个数值点，导出 CSV，创建原生 Report，并全新重开求解工程。 |
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

## 截图之外的证据

维护中的真实主机验收覆盖 Linux 上的 AEDT 2026 R1，包括安装/Display
身份、工程创建与检查、持久化任务、非覆盖工作区、全新重开、类型化断言
和产物哈希。见
[脱敏 AEDT 2026 R1 验收](docs/VALIDATION_AEDT_2026R1_LINUX.md)。

维护中的建模到结果验收从空白 HFSS 3D Layout 工程开始，创建一个合成的
三层双端口版图，执行明确的五频点扫频，导出精确 CSV 数据，在 AEDT 中
创建原生 Report，并在全新重开后再次找到相同结果。见
[脱敏完整工作流证据](docs/VALIDATION_2026-08-30_HFSS3DLAYOUT_WORKFLOW.md)。

上面的原生 Report 是有用的可视证据，但单张截图仍不能证明电气正确、网格、
收敛或求解完成。维护中的验收还会独立核对完整工程 Bundle、端口、Setup、
五个有限频点、导出的 CSV、求解产物，以及全新重开后仍然存在的同一 Report。

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

## 下一步

- 受治理地调用版本匹配的官方 PyAEDT、PyEDB 和原生 API，避免每增加
  一种几何、端口、求解或报告功能就新增一个 Bridge wrapper；
- 通过这条通用路径完成更丰富的衬底、参数化模型、场、网格、收敛、
  提取、优化和报告任务，并只把高价值、高复用流程提升为认证 workflow。

## 更多信息

- [能力与证据矩阵](docs/CAPABILITY_MATRIX.md)
- [Operation 分类与迁移判断](docs/OPERATION_CLASSIFICATION.md)
- [候选工作区生命周期](docs/WORKSPACE_LIFECYCLE.md)
- [执行上下文契约](docs/EXECUTION_CONTEXT_CONTRACT.md)
- [架构](docs/ARCHITECTURE.md)
- [版本契约](docs/RELEASE_CONTRACT.md)
- [安全策略](SECURITY.md)
- [脱敏 Linux 验收](docs/VALIDATION_AEDT_2026R1_LINUX.md)
- [脱敏 HFSS 3D Layout 建模到结果验收](docs/VALIDATION_2026-08-30_HFSS3DLAYOUT_WORKFLOW.md)
