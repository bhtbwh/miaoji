# 秒记

一个自用的本地会议记录 App/PWA。第一阶段已实现核心链路：

```text
手机/电脑浏览器录音 -> WebSocket 发到本地电脑 -> FunASR 流式转写 -> 页面实时显示 -> 本地保存 WAV 和逐字稿
```

## 当前功能

- 手机或电脑网页录音
- 音频转为 16k 单声道 PCM 后实时传到本地服务
- 后端调用 `FunASR paraformer-zh-streaming`
- 实时显示转写片段
- 保存会议音频：`data/meetings/<会议ID>/audio.wav`
- 保存逐字稿：`data/meetings/<会议ID>/transcript.txt`
- 保存会议元数据：`data/meetings/<会议ID>/meeting.json`
- PWA manifest 和离线静态资源缓存
- Windows 新电脑一键安装、启动、自检
- 架构守卫脚本，防止核心链路漂移

## 新电脑快速开始

把项目复制到新电脑后，真实转写的一键首次运行是：

```powershell
cd 秒记
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\first-run.ps1
```

它会做这些事：

- 创建 `.venv`
- 安装 Python 依赖
- 生成手机 HTTPS 证书
- 下载并初始化 `FunASR paraformer-zh-streaming`
- 启动真实转写服务

如果只是先验证页面、手机访问、麦克风权限，不下载真实模型：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\first-run.ps1 -Mock
```

如果只想安装依赖，不启动：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\setup-windows.ps1
```

脚本会打印两个地址：

```text
Desktop URL: https://localhost:8765
Phone URL:   https://<电脑局域网IP>:8765
```

后续日常使用，真实转写启动：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start.ps1
```

网络或模型缓存不稳定时，先用 `first-run.ps1 -Mock` 跑通页面和手机录音权限。

## 环境自检

```powershell
.\scripts\check-env.ps1
```

会检查：

- Python / `.venv`
- 核心依赖
- FunASR 是否可 import
- OpenSSL 和 HTTPS 证书
- 局域网 IP

## 本机开发启动

HTTP：

```powershell
.\scripts\start.ps1 -Http
```

HTTPS：

```powershell
.\scripts\start.ps1
```

另一个不依赖麦克风权限的链路测试：

```powershell
python scripts\smoke-ws.py "ws://127.0.0.1:8765/ws/record?title=smoke" 10
```

这个脚本会生成 16k PCM 音频流，直接打到 WebSocket。做 2 小时稳定性压测时，把最后的秒数改成 `7200`。

## 手机访问

手机麦克风权限通常要求 HTTPS。`setup-windows.ps1` 和 `start.ps1` 会自动检测局域网 IP 并生成证书。

如果电脑 IP 改了，重新生成证书：

```powershell
.\scripts\create-local-cert.ps1 -IpAddress 192.168.1.23
```

用 HTTPS 启动：

```powershell
.\scripts\start.ps1
```

手机浏览器打开：

```text
https://192.168.1.23:8765
```

首次访问会提示证书不受信任，手动继续访问即可。若浏览器仍拒绝麦克风权限，后续可以换成受信任的本地证书工具，比如 mkcert。

如果手机打不开电脑地址：

- 确认手机和电脑在同一 Wi-Fi。
- 确认 Windows 防火墙允许 Python/Uvicorn 访问专用网络。
- 先用电脑打开 `https://localhost:8765` 确认服务已启动。

## 真实转写配置

默认配置在 `server/config.py`：

- 模型：`paraformer-zh-streaming`
- 版本：`v2.0.4`
- 采样率：`16000`
- 设备：`cpu`
- chunk：`[0, 10, 5]`，约 600ms

可用环境变量覆盖：

```powershell
$env:MIAOJI_ASR_DEVICE = "cpu"
$env:MIAOJI_ASR_MODEL = "paraformer-zh-streaming"
$env:MIAOJI_ASR_REVISION = "v2.0.4"
.\scripts\run-dev.ps1
```

AMD 显卡环境先建议 CPU 跑通稳定性。后面若要尝试 DirectML/ROCm，需要单独评估 PyTorch 和 FunASR 兼容性。

## 下一阶段接口预留

`meeting.json` 已包含滚动摘要状态：

```json
{
  "会议摘要": [],
  "决策事项": [],
  "待办事项": [],
  "每个人负责什么": [],
  "风险/问题": []
}
```

第二阶段可以增加一个摘要 worker：每 1-3 分钟读取新增 transcript segment，调用 LM Studio 或讯飞星辰模型，持续更新这个结构。

## 防漂移验证

每次改动后运行：

```powershell
.\scripts\verify.ps1
```

如果系统禁止运行脚本：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\verify.ps1
```

它会执行：

- 架构守卫：`scripts\guard-architecture.py`
- Python 编译检查
- 标准库单元测试
- 前端 JS 语法检查

架构边界见：

- `docs/ARCHITECTURE.md`
- `docs/ROADMAP.md`
