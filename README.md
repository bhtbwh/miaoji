# 秒记

一个自用的本地会议记录 App/PWA。第一阶段已实现核心链路：

```text
手机/电脑浏览器录音 -> WebSocket 发到本地电脑 -> FunASR 流式转写 -> 页面实时显示 -> 可选滚动摘要 -> 可选会后正式纪要 -> 本地保存 WAV、逐字稿和会议 JSON
```

## 当前功能

- 手机或电脑网页录音
- 音频转为 16k 单声道 PCM 后实时传到本地服务
- 后端调用 `FunASR paraformer-zh-streaming`
- 实时显示转写片段
- 保存会议音频：`data/meetings/<会议ID>/audio.wav`
- 保存逐字稿：`data/meetings/<会议ID>/transcript.txt`
- 保存会议元数据：`data/meetings/<会议ID>/meeting.json`
- 可选实时滚动摘要：会议摘要、决策事项、待办事项、每个人负责什么、风险/问题
- 可选会后正式纪要：使用独立模型配置生成 Markdown 纪要
- 可选会后说话人分离：本地离线生成 `Speaker 1/2/3` 标签
- PWA manifest 和离线静态资源缓存
- Windows 新电脑一键安装、启动、自检
- 架构守卫脚本，防止核心链路漂移

## 新电脑快速开始

下面命令都可以在刚打开的 PowerShell 里直接运行；默认安装到：

```powershell
$HOME\Documents\秒记
```

如果你把项目放到了别的位置，把命令里的 `$HOME\Documents\秒记` 换成实际路径即可。

首次安装并启动真实转写：

```powershell
if (!(Test-Path "$HOME\Documents\秒记\.git")) { git clone https://github.com/bhtbwh/miaoji.git "$HOME\Documents\秒记" } else { git -C "$HOME\Documents\秒记" pull }; powershell -NoProfile -ExecutionPolicy Bypass -File "$HOME\Documents\秒记\scripts\first-run.ps1"
```

它会做这些事：

- 从 GitHub 下载项目到 `$HOME\Documents\秒记`
- 创建 `.venv`
- 安装 Python 依赖
- 生成手机 HTTPS 证书
- 下载并初始化 `FunASR paraformer-zh-streaming`
- 启动真实转写服务

快速验证页面、手机访问、麦克风权限，不下载真实模型：

```powershell
if (!(Test-Path "$HOME\Documents\秒记\.git")) { git clone https://github.com/bhtbwh/miaoji.git "$HOME\Documents\秒记" } else { git -C "$HOME\Documents\秒记" pull }; powershell -NoProfile -ExecutionPolicy Bypass -File "$HOME\Documents\秒记\scripts\first-run.ps1" -Mock
```

首次只安装依赖和证书，不启动：

```powershell
if (!(Test-Path "$HOME\Documents\秒记\.git")) { git clone https://github.com/bhtbwh/miaoji.git "$HOME\Documents\秒记" } else { git -C "$HOME\Documents\秒记" pull }; powershell -NoProfile -ExecutionPolicy Bypass -File "$HOME\Documents\秒记\scripts\setup-windows.ps1"
```

日常启动：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "$HOME\Documents\秒记\scripts\start.ps1"
```

更新到 GitHub 最新版本：

```powershell
git -C "$HOME\Documents\秒记" pull
```

脚本会打印两个地址：

```text
Desktop URL: https://localhost:8765
Phone URL:   https://<电脑局域网IP>:8765
```

网络或模型缓存不稳定时，先用 `first-run.ps1 -Mock` 跑通页面和手机录音权限。

## 环境自检

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "$HOME\Documents\秒记\scripts\check-env.ps1"
```

会检查：

- Python / `.venv`
- 核心依赖
- FunASR 是否可 import
- OpenSSL 和 HTTPS 证书
- 局域网 IP
- 摘要开关、模型、API Key 提示
- 正式纪要模型、API Key 提示
- 说话人分离命令提示

摘要、正式纪要和说话人分离配置缺失只会提示，不会阻止实时转写启动。

## 本机开发启动

HTTP：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "$HOME\Documents\秒记\scripts\start.ps1" -Http
```

HTTPS：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "$HOME\Documents\秒记\scripts\start.ps1"
```

另一个不依赖麦克风权限的链路测试：

```powershell
& "$HOME\Documents\秒记\.venv\Scripts\python.exe" "$HOME\Documents\秒记\scripts\smoke-ws.py" "ws://127.0.0.1:8765/ws/record?title=smoke" 10
```

这个脚本会生成 16k PCM 音频流，直接打到 WebSocket。做 2 小时稳定性压测时，把最后的秒数改成 `7200`。

## 手机访问

手机麦克风权限通常要求 HTTPS。`setup-windows.ps1` 和 `start.ps1` 会自动检测局域网 IP 并生成证书。

如果电脑 IP 改了，重新生成证书：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "$HOME\Documents\秒记\scripts\create-local-cert.ps1" -IpAddress 192.168.1.23
```

用 HTTPS 启动：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "$HOME\Documents\秒记\scripts\start.ps1"
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
powershell -NoProfile -ExecutionPolicy Bypass -File "$HOME\Documents\秒记\scripts\run-dev.ps1"
```

AMD 显卡环境先建议 CPU 跑通稳定性。后面若要尝试 DirectML/ROCm，需要单独评估 PyTorch 和 FunASR 兼容性。

## 实时摘要配置

实时摘要默认关闭。要启用火山方舟 OpenAI-compatible 接口，在本机 PowerShell 设置环境变量：

```powershell
$env:MIAOJI_SUMMARY_ENABLED = "1"
$env:MIAOJI_SUMMARY_BASE_URL = "https://ark.cn-beijing.volces.com/api/coding/v3"
$env:MIAOJI_SUMMARY_MODEL = "doubao-seed-2.0-lite"
$env:MIAOJI_SUMMARY_API_KEY = "<你的本机 API Key>"
$env:MIAOJI_SUMMARY_INTERVAL_SECONDS = "15"
$env:MIAOJI_SUMMARY_MIN_NEW_CHARS = "80"
powershell -NoProfile -ExecutionPolicy Bypass -File "$HOME\Documents\秒记\scripts\start.ps1"
```

密钥只从本机环境变量读取，不要写进仓库、脚本或日志。

`meeting.json` 会持续保存滚动摘要状态：

```json
{
  "会议摘要": [],
  "决策事项": [],
  "待办事项": [],
  "每个人负责什么": [],
  "风险/问题": []
}
```

还会保存 `rolling_summary_history` 和 `summary_status`。“每个人负责什么”只在逐字稿里明确出现姓名、称呼、负责人或 `Speaker 1/2/3` 编号时提取，不靠模型猜真实姓名。

## 会后正式纪要配置

正式纪要和实时滚动摘要是两套模型配置。实时摘要适合快模型；正式纪要可以用更强但更慢的模型。

```powershell
$env:MIAOJI_FINAL_SUMMARY_ENABLED = "1"
$env:MIAOJI_FINAL_SUMMARY_BASE_URL = "https://ark.cn-beijing.volces.com/api/coding/v3"
$env:MIAOJI_FINAL_SUMMARY_MODEL = "doubao-seed-2.0-lite"
$env:MIAOJI_FINAL_SUMMARY_API_KEY = "<你的本机 API Key>"
$env:MIAOJI_FINAL_SUMMARY_TIMEOUT_SECONDS = "180"
powershell -NoProfile -ExecutionPolicy Bypass -File "$HOME\Documents\秒记\scripts\start.ps1"
```

会议录完后，在历史会议里点“生成纪要”。成功后点“查看纪要”打开：

```text
/api/meetings/<会议ID>/minutes.md
```

正式纪要会写入 `meeting.json` 的 `final_summary`、`final_summary_markdown` 和 `final_summary_status`。生成失败只写错误状态，不覆盖已有纪要，也不影响录音、转写和实时摘要。

## 会后说话人分离

第一版只做会后离线分离，不影响录音和实时转写。页面历史会议里点“说话人分离”，成功后导出的逐字稿会带：

```text
[Speaker 1] 这是一段发言。
[Speaker 2] 这是另一段发言。
```

真实 3D-Speaker 命令是可选配置；未配置时按钮会提示错误，但转写照常可用。测试或演示可用 mock：

```powershell
$env:MIAOJI_DIARIZATION_MOCK = "1"
powershell -NoProfile -ExecutionPolicy Bypass -File "$HOME\Documents\秒记\scripts\start.ps1"
```

真实命令按本机 3D-Speaker 安装位置配置：

```powershell
$env:MIAOJI_DIARIZATION_COMMAND = "python C:\path\to\3D-Speaker\speakerlab\bin\infer_diarization.py --wav {wav} --out_dir {out_dir}"
powershell -NoProfile -ExecutionPolicy Bypass -File "$HOME\Documents\秒记\scripts\start.ps1"
```

## 防漂移验证

每次改动后运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "$HOME\Documents\秒记\scripts\verify.ps1"
```

它会执行：

- 架构守卫：`scripts\guard-architecture.py`
- Python 编译检查
- 标准库单元测试
- 前端 JS 语法检查

架构边界见：

- `docs/ARCHITECTURE.md`
- `docs/ROADMAP.md`
