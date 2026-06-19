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

- 每 1-3 分钟处理新增转写片段。
- 维护结构化滚动摘要状态。
- 摘要模型可选 LM Studio 或讯飞星辰 Coding Plan。

约束：

- 摘要 worker 不阻塞录音和 ASR。
- 摘要失败不影响 transcript 保存。
- 输入来自 `meeting.json` transcript 或 `transcript.txt`。

## 第三阶段：会后总结

目标：

- 合并完整逐字稿、滚动摘要历史、决策/待办/风险。
- 生成正式会议纪要。
- 支持 Markdown / Word / PDF 导出。

## 第四阶段：体验完善

目标：

- 会议列表、详情页、搜索逐字稿。
- 一键导出。
- 手机添加到桌面。
- 本地历史会议管理。
