# dify-win-agent

这是一个安装在 Windows 主机上的轻量 HTTP agent，用于接收 Dify Chatflow 下发的巡检命令，在本机执行后返回结构化结果，并生成详细日志与 docx 执行报告。

## 当前能力

- 本地控制台页面：GET /
- 健康检查接口：GET /health
- 命令执行接口：POST /api/v1/execute
- 报告下载接口：GET /api/v1/reports/{task_id}
- 本地最近产物下载：GET /api/v1/runtime/artifacts/{logs|reports}/{file_name}
- Windows 自提权控制流
- 默认窗口版 exe 承载控制台页面，可按需退回浏览器模式

## 运行目录

- doc：运行日志目录，启动后自动创建
- document：docx 执行报告目录，启动后自动创建

这些目录属于运行时产物，不再建议放进代码仓库。

## 配置来源

程序按下面的优先级读取配置：

1. 环境变量
2. dify-win-agent.settings.json
3. 内置默认值

settings 文件默认位于程序根目录，也可以通过环境变量改路径。

## 环境变量

- DIFY_WIN_AGENT_HOST：可选，默认 0.0.0.0
- DIFY_WIN_AGENT_PORT：可选，默认 8765
- DIFY_WIN_AGENT_COMMAND_TIMEOUT_SECONDS：可选，默认 300
- DIFY_WIN_AGENT_LOG_DIR：可选，默认 doc
- DIFY_WIN_AGENT_REPORT_DIR：可选，默认 document
- DIFY_WIN_AGENT_SETTINGS_PATH：可选，自定义 settings 文件路径
- DIFY_WIN_AGENT_WINDOW_MODE：可选；仅 exe 模式生效，默认 1，设为 0 切回浏览器模式
- DIFY_WIN_AGENT_OPEN_BROWSER：可选；仅在关闭窗口模式后才生效，默认 1

## 安装依赖

运行依赖和打包依赖：

```powershell
python -m pip install -r requirements.txt
```

本地测试依赖：

```powershell
python -m pip install -r requirements-dev.txt
```

## 本地运行

```powershell
$env:PYTHONPATH = "src"
python src/main.py
```

## 本地控制台页面

启动后可访问 http://127.0.0.1:8765/ 。如果使用打包后的 exe，程序默认会直接打开原生窗口；如关闭窗口模式，则退回系统浏览器。

页面当前展示：

- 可折叠侧边栏：快捷入口、接口说明、本机信息
- 四个主板块：运行概况、运行设置、最近产物、控制台实时日志
- 日志目录/报告目录的目录选择器
- 最近日志和最近报告的可点击下载列表
- 实时滚动的日志尾部预览

这套页面不改变现有 Dify 调用协议。

## HTTP 接口

### GET /

返回本地控制台页面，适合 exe 启动后的本机运维查看。

### GET /health

返回：

```json
{
  "status": "ok",
  "service": "dify-win-agent",
  "process_id": 61128,
  "started_at_utc": "2026-05-21T01:53:32.533217Z",
  "checked_at_utc": "2026-05-21T01:53:44.459300Z",
  "uptime_seconds": 11
}
```

说明：

- 固定返回 no-store/no-cache 响应头
- process_id、started_at_utc、uptime_seconds 可用于判断是否已经切到新进程
- 当前默认无鉴权

### POST /api/v1/execute

请求体：

```json
{
  "task_id": "task-001",
  "target_host": "10.0.0.5",
  "commands": [
    {
      "id": "cmd-001",
      "shell": "whoami"
    }
  ]
}
```

响应体：

```json
{
  "status": "succeeded",
  "message": "命令执行完成。",
  "task_id": "task-001",
  "target_host": "10.0.0.5",
  "report_download_url": "/api/v1/reports/task-001",
  "command_results": [
    {
      "command_id": "cmd-001",
      "shell": "whoami",
      "return_code": 0,
      "stdout": "administrator\n",
      "stderr": ""
    }
  ]
}
```

说明：

- status 可能为 succeeded、partially_failed、failed
- message 为中文摘要，适合直接给 Dify 的分支或回复节点使用
- 更细的排障信息以 command_results、doc 日志和 document 报告为准
- 当前默认无鉴权

### GET /api/v1/reports/{task_id}

返回指定任务的 docx 执行报告。

### GET /api/v1/runtime/artifacts/{artifact_kind}/{file_name}

仅供本地控制台页面下载最近日志和最近报告使用，不属于 Dify 主链路接口。

## 运行测试

```powershell
$env:PYTHONPATH = "src"
python -m pytest -q
```

## 打包 exe

```powershell
./scripts/build.ps1
```

默认产物为窗口版单文件 exe：dist/dify-win-agent.exe。

说明：

- 程序带管理员权限清单，首次运行会触发 UAC
- 程序根目录下生成的 doc、document、dify-win-agent.settings.json 都属于本地运行产物
- build/dify-win-agent、.pytest_cache、*.spec 也都属于本地构建/测试产物

## Dify 对接文档

- Chatflow 搭建与节点建议见 [docs/dify-chatflow-setup.md](docs/dify-chatflow-setup.md)
- 命令库环境变量模板见 [docs/dify-command-library.json](docs/dify-command-library.json)

其中 COMMAND_LIBRARY_JSON 只作为 Dify 环境变量内容的参考模板，不属于 Win Agent 本地配置。
