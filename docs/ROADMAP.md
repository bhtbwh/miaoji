# 路线图

## 当前阶段：新电脑和手机可直接用

目标：

- 新 Windows 电脑解压项目后，能一键安装依赖。
- 一键启动本地服务。
- 自动打印电脑端和手机端访问地址。
- 手机通过 HTTPS 打开后可以录音。
- 有自检和回归脚本避免改坏核心链路。

交付：

- `scripts/setup-windows.ps1`
- `scripts/start.ps1`
- `scripts/start-mock.ps1`
- `scripts/check-env.ps1`
- `scripts/verify.ps1`
- `scripts/guard-architecture.py`

## 第一阶段稳定性

目标：

- `FunASR paraformer-zh-streaming` CPU 跑通。
- 手机录音稳定 2 小时。
- 音频和逐字稿完整落盘。

验证：

```powershell
python scripts\smoke-ws.py "ws://127.0.0.1:8765/ws/record?title=stability" 7200
```

## 第二阶段：实时摘要

目标：

- 每 15 秒检查新增正式转写片段，累计约 80 字以上才调用摘要模型。
- 维护结构化滚动摘要状态和更新历史。
- 摘要模型使用 OpenAI-compatible 接口，可接火山方舟、LM Studio 或其他兼容服务。

约束：

- 摘要 worker 不阻塞录音和 ASR。
- 摘要失败不影响 transcript 保存。
- 输入来自 `meeting.json` transcript 或 `transcript.txt`。
- 固定输出五类：会议摘要、决策事项、待办事项、每个人负责什么、风险/问题。
- 负责人只在逐字稿明确出现姓名、称呼、负责人或 Speaker 编号时提取。

## 会后说话人分离

目标：

- 会议结束后手动触发本地离线说话人分离。
- 生成 `Speaker 1/2/3` 标签并回写 `meeting.json`。
- 导出的逐字稿保留 speaker 标签。

约束：

- 不进入实时录音和 ASR 主链路。
- 第一版不识别真实姓名，只显示编号。
- 真实 3D-Speaker 命令可选配置；缺失时不影响转写。

## 第三阶段：会后总结

目标：

- 合并完整逐字稿、滚动摘要历史、决策/待办/风险。
- 使用独立 `MIAOJI_FINAL_SUMMARY_*` 模型配置生成正式会议纪要。
- 支持 Markdown 导出。

约束：

- 不进入实时录音和 ASR 主链路。
- 生成失败只写入 `final_summary_status`，不覆盖已有纪要。
- 第一版不让模型猜真实姓名；如果有说话人标签，只使用 `Speaker 1/2/3`。
- Word / PDF 导出留到体验完善阶段。

## 第四阶段：体验完善

目标：

- 会议列表、详情页、搜索逐字稿。
- 一键导出。
- 手机添加到桌面。
- 本地历史会议管理。
