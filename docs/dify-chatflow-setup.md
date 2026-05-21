# Dify Chatflow 搭建说明

## 目标和边界

这条 Chatflow 的职责是理解用户问题、判断是否需要执行命令、决定是否进入人工审批、调用 Win Agent，并把执行结果整理成最终回复。

当前 Win Agent 只负责四类能力：

- GET /：本机控制台页面
- GET /health：健康检查
- POST /api/v1/execute：执行命令
- GET /api/v1/reports/{task_id}：下载 docx 执行报告

不要把 COMMAND_LIBRARY_JSON 写进 Win Agent 本地环境变量；它只应该存在于 Dify 环境变量中。

## 联调前提

- Windows agent 必须监听可被 Dify 访问的地址，不能只绑定 127.0.0.1
- 推荐将 DIFY_WIN_AGENT_HOST 设置为 0.0.0.0，并在 Dify 中使用该机器的实际 IPv4 地址和端口
- Windows 防火墙需要放行 agent 监听端口，默认示例为 TCP 8765
- 对接前先确认 Dify 所在环境能访问 http://{machine_ip}:{win_agent_port}/health

## 推荐开始节点输入

- machine_ip：必填；Win Agent 所在 Windows 机器 IP，例如 10.0.18.212
- win_agent_port：必填；Win Agent 监听端口，默认 8765

说明：在当前 Chatflow 形态下，开始节点输入会作为每轮运行的入口参数。最稳妥的做法是每轮真实用户请求进入后都先做一次 /health 检查，而不是依赖写死的固定地址。

## 推荐工作流主干

1. 开始
2. 拼接 Agent 地址
3. 地址校验代码节点
4. If-Else：地址是否可用
5. 健康检查 HTTP 节点
6. 健康检查结果校验代码节点
7. If-Else：健康检查是否通过
8. 请求路由节点
9. 直接问答分支：知识检索 + LLM
10. 巡检规划 Agent
11. 风险复核或人工审批
12. 规范化执行请求
13. 执行请求体校验
14. execute HTTP 节点
15. execute 结果校验代码节点
16. 执行结果整理节点
17. 整理最终答复节点
18. 唯一最终答复节点

推荐保持单一最终答复出口，不要把多个失败文案直接挂在不同 answer 节点上，避免流式模式下相互污染。

## 建议环境变量

- COMMAND_LIBRARY_JSON：复制 [docs/dify-command-library.json](docs/dify-command-library.json) 的完整内容
- RISK_KEYWORDS：高风险关键词数组，建议至少包含 remove、disable、delete、restart、stop-service、set-ad、clear、reset

说明：COMMAND_LIBRARY_JSON 是参考命令库，不是硬性白名单。规划 Agent 可以优先复用其中已有的安全包装命令，但命令库不足时，允许它生成新的只读巡检或排障命令。

## 节点配置建议

### 拼接 Agent 地址

- 输出 base_url = http://{machine_ip}:{win_agent_port}
- 所有后续 HTTP 节点都引用这个输出，避免多处手填地址

### 健康检查 HTTP 节点

- Method：GET
- URL：{{ base_url }}/health
- 成功后只把 status、process_id、started_at_utc、uptime_seconds 传给后续节点

健康检查失败时，优先提示检查 machine_ip、win_agent_port、进程是否运行、防火墙是否放行；不要直接混入 execute 失败文案。

### 请求路由 / 巡检规划 Agent

建议把问题分成四类：

- direct_answer：解释命令、解释报告、解释巡检项，不执行命令
- full_inspection：明确要求全量检查
- targeted_inspection：只检查某个组件或某个故障现象
- missing_context：缺少目标地址、范围或上下文

规划 Agent 输入建议：

- 用户原始问题
- machine_ip
- 结构化提取结果
- COMMAND_LIBRARY_JSON
- 风险规则

提示词里至少约束三点：

- 优先理解用户真实目标，再决定是否需要执行命令
- commands 中每一项都必须包含 id 和 shell
- 如涉及高风险动作，必须明确给出 risk_level=high 和人工审批所需说明

推荐输出 JSON 结构：

```json
{
	"task_id": "{{ conversation_id }}-{{ sys.time }}",
	"target_host": "{{ machine_ip }}",
	"route_mode": "execute",
	"risk_level": "low",
	"reason": "用户要求检查 AD 复制状态",
	"commands": [
		{
			"id": "ad_repadmin_summary",
			"shell": "repadmin /replsummary"
		}
	]
}
```

### 人工审批节点

当 risk_level = high 时进入人工审批或显式阻断分支。表单里至少展示：

- 拟执行命令
- 命令用途
- 风险原因
- 可人工替代的命令
- 拒绝后是否仍允许执行低风险前置检查

### execute HTTP 节点

- Method：POST
- URL：{{ base_url }}/api/v1/execute
- Content-Type：application/json

当前 Win Agent 默认无鉴权，不需要再传旧的 Authorization 请求头。

请求体示例：

```json
{
	"task_id": "{{ conversation_id }}-{{ sys.time }}",
	"target_host": "{{ machine_ip }}",
	"commands": {{ approved_commands_json }}
}
```

关键响应字段：

- status：succeeded、partially_failed、failed
- message：中文摘要
- report_download_url：报告下载路径
- command_results：原始命令执行结果数组

建议将两类失败严格区分：

- 健康检查失败：网络、地址、端口、SSRF 或服务未启动问题
- execute.status = failed：Win Agent 已收到请求，但命令本身全部失败，应聚焦权限、主机角色、工具缺失或命令报错

### 下载报告 HTTP 节点

- Method：GET
- URL：{{ base_url }}{{ execute.report_download_url }}
- 将响应保存为文件变量，例如 report_file

当前 Win Agent 默认无鉴权，不需要再传旧的 Authorization 请求头。

优先使用 Dify 原生附件能力输出 report_file，不要再走 Markdown 下载链接。

### 整理最终答复节点

建议统一汇聚这些终态分支：

- 直接问答
- 参数不足
- 健康检查失败
- 高风险审批驳回或超时
- execute 失败
- execute 部分失败
- execute 成功

最终回复最好固定包含：

- 巡检结论
- 执行状态
- 关键发现
- 若有失败，给出失败原因和下一步建议
- 若有报告文件，直接附加 report_file

## 常见失败提示口径

- 参数不足：缺少机器地址或巡检范围，请补充后重试
- Agent 不可达：请确认服务是否启动、端口是否开放、Dify 是否能访问该地址
- 命令超时：检查目标主机负载、命令耗时，或适当增大 DIFY_WIN_AGENT_COMMAND_TIMEOUT_SECONDS
- 报告下载失败：命令可能已执行，但报告文件未成功回传，请检查 document 目录与报告下载接口

迁移提醒：如果旧 workflow 里还保留 WIN_AGENT_API_KEY 环境变量或 Authorization 头，建议一并删除，避免形成误导。

## 与当前 Win Agent 接口对齐

- GET / 是本机控制台页面，只用于人工查看，不属于 Dify 必需链路
- GET /health 用于每轮运行前的连通性检查
- POST /api/v1/execute 是唯一执行入口
- GET /api/v1/reports/{task_id} 用于取回 docx 执行报告
