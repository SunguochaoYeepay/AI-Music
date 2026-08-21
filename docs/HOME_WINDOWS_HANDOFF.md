# 家里 Windows 电脑接管手册

本文给接管该项目的 AI 或操作人员使用。目标是让家里 Windows 电脑承担：

1. 每天 10:30 读取趋势、生成至少 3 首候选歌曲及 Flux 封面，并同步个人飞书。
2. 自动对账用户的审听结果，生成发行包。
3. 为审核通过的歌曲生成 H3 循环音乐视频；外部平台发布仍由用户确认。

## 先看结论

- GitHub 只保存代码和不含凭证的模板。
- `config.json`、`resource_library/`、`temp/`、日志不进 Git。
- 每日趋势分析和三首歌曲生成需要 Codex 自动化；它不是普通 Python 定时脚本。
- 视频生产已经是可独立定时运行的 Python 工程脚本。
- 不得使用易宝支付账号、应用或数据，只能使用用户的个人飞书账号和个人 Wiki。

## 1. 拉取正确代码

当前完整视频自动化位于分支：

```powershell
git clone --branch codex/automate-music-video-pipeline https://github.com/SunguochaoYeepay/AI-Music.git
Set-Location AI-Music
git status
```

在该分支合并进 `main` 以后，后续新机器可改为普通 `git clone`。更新代码：

```powershell
git pull --ff-only
```

不要在接管时运行会覆盖本地数据的 Git 清理命令。`resource_library/` 是正式资产库。

## 2. 安装依赖

需要安装并加入 `PATH`：

- Python 3.10 或更高版本
- Git
- FFmpeg（同时需要 `ffprobe`）
- Node.js 与 npm
- 飞书 CLI

```powershell
npm install -g @larksuite/cli@latest
python --version
ffmpeg -version
ffprobe -version
lark-cli --version
```

项目主要使用 Python 标准库，不需要额外 `pip install`。先运行测试：

```powershell
python -m unittest discover -s tests -v
```

## 3. 确认本机 ComfyUI

家里电脑上的 ComfyUI 应能访问：

```text
http://127.0.0.1:8188
```

浏览器打开该地址，并确认 `/queue` 和 `/object_info` 可访问。模型和节点至少包括：

- MiniMax Music 3：扩散模型、文本编码器、VAE、`MiniMaxMusic3TextEncode`
- Flux：UNET、双文本编码器、VAE、Flux 专用采样链
- MiniMax H3：FL2VA 模型、视频/音频 VAE、Turbo 加速 LoRA 及相关节点

生成音乐和封面时，ComfyUI 必须保持开启。关机或离线时任务应等待下次重试，不能重复提交。

## 4. 配置私有文件

`config.json` 被 Git 忽略。不要把它、密码、应用密钥或飞书令牌提交到 GitHub。

从旧电脑通过安全方式单独复制 `config.json`，或者：

```powershell
Copy-Item config.example.json config.json
```

然后填写：

```json
{
  "comfyui_url": "http://127.0.0.1:8188",
  "feishu": {
    "cli": "lark-cli",
    "base_token": "<个人飞书 Wiki 对应的 Base token>",
    "base_url": "<个人飞书 Wiki URL>",
    "music_table_id": "<音乐生产表 ID>",
    "release_table_id": "<发布数据表 ID>",
    "video_table_id": "<新媒体视频表 ID>"
  },
  "resource_library": "resource_library"
}
```

用个人飞书身份重新授权：

```powershell
lark-cli auth login --domain base,wiki,drive
lark-cli auth status
```

授权页面必须显示个人账号，不得出现易宝支付组织身份。

## 5. 迁移正式媒体资源

GitHub 不保存音频、封面、发行 WAV 或视频。要延续已有歌曲，必须把旧电脑的整个目录单独复制到新仓库：

```text
resource_library/
```

不要只复制 MP3。每个歌曲目录应至少保留：

```text
audio_master.flac
audio_320k.mp3
cover_1024.png
manifest.json
release/                 已审批歌曲可能存在
video_music_1080p.mp4    已生成视频的歌曲可能存在
```

复制完成后，抽查文件：

```powershell
Get-ChildItem resource_library -Directory
ffprobe resource_library\<歌曲ID>\audio_master.flac
```

未迁移资源库时，不得把飞书中已有歌曲误判为本地丢失并重新生成。

## 6. 配置每日 Codex 自动化

在家里电脑的 Codex 中打开本仓库，创建每天 10:30 执行的现有任务自动化。使用：

```text
docs/DAILY_AUTOMATION_PROMPT_TEMPLATE.md
```

先替换文件顶部列出的全部占位符，再把正文作为自动化提示词。该自动化负责：

- 读取热点与日历并写入趋势雷达。
- 审听结果对账。
- 顺序生成至少三首歌曲和三张封面。
- 校验、归档、清理临时目录并同步飞书。

Codex 自动化是线程连续任务。迁移后第一天应人工观察完整运行一次，确认它使用的是家里仓库和本机 ComfyUI。

## 7. 配置 Windows 视频定时任务

视频脚本只处理“审听结果=通过”且缺少有效视频的歌曲，具备幂等检查。先预览：

```powershell
python -m scripts.run_video_automation --config config.json
```

确认队列后手工执行一次：

```powershell
python -m scripts.run_video_automation --config config.json --apply
```

验证成功后，用管理员 PowerShell 注册定时任务。以下命令需在仓库根目录执行：

```powershell
$repo = (Get-Location).Path
$python = (Get-Command python).Source
$arguments = "-m scripts.run_video_automation --config `"$repo\config.json`" --apply"
$action = New-ScheduledTaskAction -Execute $python -Argument $arguments -WorkingDirectory $repo
$triggers = @(
  (New-ScheduledTaskTrigger -Daily -At "10:30")
  (New-ScheduledTaskTrigger -Daily -At "12:30")
  (New-ScheduledTaskTrigger -Daily -At "15:30")
  (New-ScheduledTaskTrigger -Daily -At "19:30")
  (New-ScheduledTaskTrigger -Daily -At "22:30")
)
Register-ScheduledTask -TaskName "AI-Music-Video-Automation" -Action $action -Trigger $triggers -Description "Generate H3 videos for approved AI music" -Force
```

这些时间中，10:30 是主运行，其他时间用于家里电脑晚开机或 ComfyUI 暂时繁忙时补偿重试。

## 8. 首次接管验收

按顺序完成以下检查：

```powershell
python -m unittest discover -s tests -v
python -m scripts.reconcile_reviews --base-token <个人 Base token> --table-id <音乐生产表 ID>
python -m scripts.run_video_automation --config config.json
```

然后确认：

- 飞书记录没有分页警告。
- 只读取个人飞书数据。
- ComfyUI 队列没有同一歌曲的重复任务。
- 已通过歌曲能复用现有发行包和视频，不重复生成。
- 新歌只在四项正式资产校验后进入 `resource_library/`。
- 外部平台发布状态仍是待确认，没有自动上传 B站、抖音或其他平台。

## 9. 日常维护

更新代码：

```powershell
git pull --ff-only
python -m unittest discover -s tests -v
```

查看定时任务：

```powershell
Get-ScheduledTask -TaskName "AI-Music-Video-Automation"
Get-ScheduledTaskInfo -TaskName "AI-Music-Video-Automation"
```

暂停视频自动化：

```powershell
Disable-ScheduledTask -TaskName "AI-Music-Video-Automation"
```

恢复：

```powershell
Enable-ScheduledTask -TaskName "AI-Music-Video-Automation"
```

## 10. 不能做的事

- 不得把 `config.json`、密码、飞书应用密钥、OAuth 令牌提交到公开仓库。
- 不得自动发布到外部平台。
- 不得把 AI 或用户擅自写成作曲、作词或出版者。
- 不得伪造 ISRC、UPC。
- 不得模仿具体艺人或歌曲。
- 不得把“经典”或“年代久远”直接当作公版。
- 不得删除已归档的正式资源；淘汰只删除飞书待办记录和对应临时目录。
