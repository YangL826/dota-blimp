# 本地 Agent 框架（blimp bot 专用）

在你 Windows 电脑上跑的"死亡分析师"：自动打包 death 记录 → 调模型分析死因 → 存报告。
**只新增这一个 `agent/` 文件夹，原项目（blimp_bot.py、analysis/、deaths/ 等）一个文件都不动。**

## 目录结构

```
agent/
  config.json      ← 改这里：项目路径、模型接口配置
  watcher.py       ← 阶段 0：监听 deaths/，自动打 zip
  analyst.py       ← 阶段 1：ReAct 循环，分析死因
  model_client.py  ← 模型调用封装（OpenAI-compatible）
  tools.py         ← 模型的"手脚"：读文件/列目录/看图/写报告
  prompts.py       ← system prompt（工作规范）
  run_watcher.bat  ← 双击运行 watcher
  run_analyst.bat  ← 双击运行 analyst
  outbox/          ← 打包好的 zip（自动生成）
  reports/         ← 分析报告（自动生成）
```

## 上手步骤

### 1. 放进去
把整个 `agent/` 文件夹解压到 `F:\claude memory\dota_blimp\` 下面。
如果你的项目路径不一样，改 `config.json` 里的 `project_root`。

### 2. 装依赖（analyst 需要，watcher 不需要）
用项目自带的 venv：
```
F:\claude memory\dota_automaton\.venv\Scripts\pip.exe install requests
```

### 3. 跑阶段 0（零配置）
双击 `run_watcher.bat`。它会一直监听 `deaths/`，
新 death 文件夹写完后自动打成 zip 放到 `agent/outbox/`。
想停就关窗口。

### 4. 填模型配置（阶段 1 需要）
本地 agent 调的不是"我"的 API——我没有对外 API。它调的是 **Meta Model API**
（dev.meta.ai，OpenAI 兼容接口，模型和我是同系列的 Muse Spark），
`config.json` 里 `base_url` 和 `model` 已经按官方文档预填好了【8831691352092911569†L41-L49】，
你只需要填 `api_key`：

1. 打开 https://dev.meta.ai/ 注册/登录
2. 找到 **API keys → Create API key**，创建一个 key【8831691352092911569†L14-L15】
3. 把 key（格式类似 `LLM|...`）粘贴到 `config.json` 的 `api_key` 里，替换掉占位文字
4. key 只存在这个文件里，别传到别处。预览期免费【8831691352092911569†L48-L49】

### 5. 冒烟测试（不花钱）
```
run_analyst.bat --dry-run
```
不调模型，只打印 system prompt 和工具列表，确认框架本身没问题。

### 6. 实战
双击 `run_analyst.bat`（分析最新的 death），或指定文件夹：
```
..\dota_automaton\.venv\Scripts\python.exe analyst.py 203238_death
```
运行时每一步都会打印：模型在想什么、调了什么工具、返回了什么。
报告存到 `agent/reports/`。

## 对照着学

这个框架是之前讲的 8 个设计点的实例：
- ReAct 循环 → `analyst.py` 的 `main()` 主循环
- 大脑/手脚/工作台 → `model_client.py` / `tools.py` / `messages` 列表
- 工具小而确定 → `tools.py` 每个 `do_*` 函数
- 最小权限护栏 → 唯一的写出口是 `write_report`，且只能写 `reports/`
- 路径防越界 → `tools._safe`
- 上下文工程 → `trim_history`（超预算丢最早回合）+ prompt 里"只挑关键帧看"
- 工具层容错 → `tools.execute` 把报错转成文字喂回模型，而不是崩溃
- 兜底 → 模型忘调 `write_report` 时自动存一份，不丢结论

## 下一步（阶段 2 预告）

分析师跑稳之后，再加：
- `write_file` 工具（带自动备份，只能写 `analysis/work.py`）
- `run_command` 工具（白名单：只允许 `python -m py_compile` 和 `test_harness.py`）
- prompt 里加"测试门"条款：errors:0 才能算改完
- 复制成 `blimp_bot.py` 之前必须人工确认（human-in-the-loop）

阶段 2 的改动也都会放在这个 `agent/` 文件夹里，原项目结构依然不动。
