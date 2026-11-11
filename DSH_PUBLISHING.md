# DSH 插件安装与市场发布

本文件对应 Deep Research Agent 0.6.0。研究逻辑沿用 0.5 的全文优先、多领域来源规划、证据与引用工具；新增加载方式为标准 DSH bundle。插件不是另一个模型，也不使用任何私人搜索索引。

## 本地安装：立即可用，不需要先上架

前提：DSH 0.2.2-rc.1（本版验证基线；声明范围 >=0.2.2-rc.1 <0.3.0）、Node >=24.9.0、Python >=3.11。用 DSH 自带的 Node 环境安装插件；Windows/WSL/容器分别配置自己的 Python。

解压 ZIP，进入 deep-research-agent 项目目录。可用绝对路径安装：

```sh
dsh plugin --profile web add /绝对路径/deep-research-agent
dsh --profile web --dump-config
dsh --profile web
```

Windows 将路径替换为自己的目录并加双引号。也可以先 `npm pack`，再安装生成的 `.tgz`：

```sh
dsh plugin --profile web add /绝对路径/dsh-deep-research-agent-0.6.0.tgz
```

上述是 DSH CLI 的安装流程，通常不需要单独执行 Python 安装器。已有 Codex、Claude Code 或 DSH 文件工作流安装可继续使用；不要在同一 DSH scope 中同时挂载同名 `deep_research` 手工 MCP 条目和本插件。移除旧手工 MCP 行，或为插件设置不同的 serverName。

插件依赖当前 profile 已提供 `skills` 和 `tools` 服务，标准 web profile 具有这些能力。它通过官方 skill-filesystem 和 mcp-client 挂载工作流与23个工具，不替换模型、原有 profile、权限规则或 API 账户。离线本地包仍需要环境中有相应 DSH peer 依赖，不能保证一个完全断网的新环境可首次安装。

## 配置和使用

首次激活插件时检查 Python 版本，并在不存在时创建私有配置：

`~/.local/share/deep-research-agent/research.env`

与原安装器共用这个位置；已存在的文件和 Key 不覆盖。文件值不包含在插件包、日志、补丁或市场提交材料中。需要其它位置可设置插件的 dataDir/envFile。只有研究实际调用到检索服务才会发出相应请求；安装/加载本身不启动深度研究。

配置项：

| 字段 | 默认与作用 |
|---|---|
| pythonCommand | Unix: python3；Windows: python；须是可执行程序，不是一整条 shell 命令 |
| pythonArgs | []；Windows py 启动器可设置 ["-3.11"] |
| dataDir | ~/.local/share/deep-research-agent，保存 runs/ 等状态 |
| envFile | dataDir/research.env，复用实际配置 |
| serverName | deep_research；同一 scope 中不能重名 |
| toolCallTimeoutMs | 120000 |

也可使用宿主进程环境变量 DEEP_RESEARCH_PYTHON、DEEP_RESEARCH_DATA_DIR、DEEP_RESEARCH_ENV_FILE。插件配置字段优先。真实搜索 Key 仍填 research.env。不会额外要求模型 Key；DSH 自身的模型服务仍需可用。

进入 DSH 后说：

```text
调用 deep-research-agent 研究「某个问题」。
优先全文与原始来源，记录重点章节、摘要降级原因及实际检索覆盖，生成带引用报告。
```

工具一般显示为 `mcp__deep_research__research_begin` 等；工作流名称仍是 deep-research-agent。报告位置以工具返回路径为准。

卸载：

```sh
dsh plugin --profile web remove dsh-deep-research-agent
```

卸载会移除 bundle 及其工具/工作流挂载，保留私有配置与研究数据，不自动删除用户报告。

## 上传 GitHub 后安装

发布仓库为 https://github.com/champeil/deep_search_agent 。把 ZIP 中 deep-research-agent 目录内的内容放到该仓库根目录，保留现有 MIT LICENSE。根目录必须直接有 package.json，不能多套一层 ZIP 目录。不要上传 node_modules、research.env、研究数据库或私人报告。

本包已写入实际仓库元数据。需要重新生成提交草稿时执行：

```sh
python scripts/prepare_dsh_release.py --repo champeil/deep_search_agent --author champeil
npm run check:plugin
npm install --ignore-scripts --no-audit --no-fund
npm test
npm run test:bridge
```

准备脚本只在本地更新 package.json 的 repository/homepage/bugs/author，生成 DSH_SUBMISSION.json 草稿；不登录、不上传、不提交审核、不代替你做所有权声明。旧 package.json 只备份一次。提交 package.json 前同步 npm lock 元数据：`npm install --package-lock-only --ignore-scripts`。草稿与备份默认不进入代码仓库。

给仓库添加 Topic：`dsh-plugin`。官方也建议用此 Topic 提高可发现性。其它建议 Topic：deepseek-harness、cordis-plugin、deep-research。

上传后安装命令：

```sh
dsh plugin --profile web add github:champeil/deep_search_agent
```

可按 DSH/GitHub 源语法固定到真实提交：`github:owner/repo#实际commit`。本包为可直接运行的 JavaScript，无 TypeScript 编译或 install/prepare 钩子，不需要用户允许本包执行构建脚本。

## npm 发布（可选，不是市场收录的前提）

本包可 `npm pack`，但尚未以你的账户发布。包名 dsh-deep-research-agent 是当前项目名，最终名称是否可用以 npm 发布时的账户与注册表为准。若改包名，须同时修改 dsh/cordis.patch.yml 的 name 行。

只有你明确选择 npm 发布并具备包名权限后，才登录并执行发布。发布前可检查：

```sh
npm run check:plugin
npm pack --dry-run --json
npm publish --dry-run
```

真正公开发布的命令为 `npm publish --access public`；它不是上面的验证命令，本交付没有执行。发布后用户才能用 `dsh plugin --profile web add npm:实际包名` 安装，当前不能把示例包名当作已上架包。

沿用仓库现有 MIT LICENSE（Copyright (c) 2026 Champeil），package.json 声明 MIT；发布包保留完整 LICENSE。

## 社区插件市场提交

DSH bundle 是安装格式；插件市场是发现/收录入口，两者分开。当前发布材料按社区 Registry `https://plugin.dshdesk.com/` 的公开规范准备，不能把它称为 DeepSeek 官方审核或官方安全背书。

该社区目录要求公开、未归档且非 Fork 的仓库，带 dsh-plugin Topic；根目录 package.json 声明 dsh.bundle.patch，patch 为包内安全相对路径且是顶层 YAML 数组。本项目已提供这个结构，本地检查不代表远程仓库或市场已经通过审核。

在 `https://plugin.dshdesk.com/publish` 填：

- 仓库 URL：https://github.com/champeil/deep_search_agent；
- GitHub 用户名：champeil；
- 至少20字符的简介；
- 确认本人是所有者/主要维护者并有权提交；
- 确认仓库、简介与补充信息会公开进入审核 Issue。

简介草稿：

> 多领域深度研究工作流：原生搜索优先、全文优先阅读、数据库检索、逐条证据与引用审阅、请求预算及覆盖记录；使用当前宿主模型。

说明草稿：

> 标准 dsh.bundle，使用官方 filesystem skill provider 和 MCP client；需要 Python 3.11+，不内置模型 Key，不含真实搜索凭据。支持23个证据工具。已做本地 manifest/patch、研究后端、Cordis/DSH 服务挂载与工具调用检查；未宣称与 Perplexity 质量等价。请核对仓库实际测试记录和版本。

按页面完成验证并提交后，需保留实际审核工单 URL；维护者审核和后续目录同步均不保证即时完成。只有拿到实际提交记录才可说“已提交审核”；只有在市场实际条目可见后才可说“已收录/上架”。其它社区市场规则可能不同，不能承诺一次提交会自动同步所有市场。

## 本交付状态与验证边界

已制作可打包的插件源码和 .tgz；尚未发布 npm、尚未上传你的 GitHub、尚未提交或获得任何市场审核。发布仓库已确定为 champeil/deep_search_agent，元数据与 MIT 许可证已同步；当前会话无 GitHub 写入连接，因此尚未完成源码上传、Topic 配置和远程收录步骤。本文 GitHub 安装命令须在源码上传完成后使用。

真实组件检查使用已发布的 @deepseek-ai/cordis 4.1.0 和 DSH 0.2.2-rc.1 系列服务：工作流可加载，23工具可发现，research_begin/search原生优先保护/status可调用，远程搜索与模型调用均为0，卸载后工具和 provider 清理成功。它不是完整Web UI或真实研究质量的端到端测试。

官方与市场参考（核对日期2026-11-11）：

- 官方 bundle： https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/develop/basic/publish.md
- 官方 MCP： https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/mcp/mcp-client/README.md
- 官方 filesystem skills： https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/skill/skill-filesystem/README.md
- 官方发现 Topic： https://github.com/deepseek-ai/deepseek-harness#community-and-support
- 社区提交： https://plugin.dshdesk.com/publish
- 社区规则： https://plugin.dshdesk.com/policy
