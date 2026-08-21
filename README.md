# AI Music Pipeline

将 MiniMax Music 3、Flux、ComfyUI 和飞书多维表格串成可迁移的音乐生产流程。

## 设计原则

- ComfyUI 负责生成，脚本负责提交、轮询、下载和校验。
- 本地资源库是音频和封面的长期资产来源，远端 URL 只作为生成源记录。
- 所有中间文件统一放在 `temp/<song_id>/`，校验归档成功后立即删除。
- 飞书 CLI 负责元数据同步，浏览器只用于人工确认。
- 不自动对外发布；发布前保留人工审批。
- 不把令牌、密码、个人绝对路径或媒体大文件提交到 Git。

## 目录

```text
ai_music_pipeline/       可复用的 Python 模块
scripts/                  命令行入口
config.example.json       配置模板，不含凭证
resource_library/         本地媒体资产（被 Git 忽略）
temp/                     生成和转码中间文件（被 Git 忽略，成功后清理）
```

## 环境

- Python 3.10+
- `ffmpeg` / `ffprobe`
- ComfyUI API 地址
- 已授权的 `lark-cli`（个人飞书身份）

家里 Windows 电脑接管项目时，请从 [docs/HOME_WINDOWS_HANDOFF.md](docs/HOME_WINDOWS_HANDOFF.md) 开始；
每日 Codex 任务使用 [docs/DAILY_AUTOMATION_PROMPT_TEMPLATE.md](docs/DAILY_AUTOMATION_PROMPT_TEMPLATE.md)。

复制配置模板后按本机环境修改：

```bash
cp config.example.json config.json
```

## 常用操作

提交一个已经展开为 API 格式的 ComfyUI workflow：

```bash
python -m scripts.comfy_submit --workflow workflow.json --wait --download-dir temp/SONG-YYYYMMDD-001
```

归档完成后清理临时目录：

```bash
python -m scripts.archive_assets \
  --temp-dir temp/SONG-YYYYMMDD-001 \
  --resource-dir resource_library/SONG-YYYYMMDD-001 \
  audio_master.flac audio_320k.mp3 cover_1024.png manifest.json
```

将一条歌曲记录写入飞书：

```bash
python -m scripts.sync_feishu --record record.json --table-id <table-id>
```

发行商提交完成后，把发行项目、状态、日期和每首曲目的 ISRC 填入一份发行清单
（格式参考 `release.example.json`），先预览再执行：

```bash
python -m scripts.register_release --release-file temp/release.json
python -m scripts.register_release --release-file temp/release.json --apply
```

该流程按 `歌曲ID` 幂等更新，不会重复创建同一首歌；同时回填本地 manifest、
`release_metadata.json` 和 `release_metadata.csv`。发行商状态变化后，修改同一份清单并重跑即可。
支持的状态为 `In Review`、`Approved`、`Needs Changes`、`Rejected`。
`distributor_status` 只表示发行商审核进度；`publication_status` 单独表示平台是否已上线。
即使发行商显示 `Approved`，在拿到 Apple Music 等平台的正式链接前仍应保持 `待发布`。

按审核结果对账（默认只预览）：

```bash
python -m scripts.reconcile_reviews --table-id <table-id>
python -m scripts.reconcile_reviews --table-id <table-id> --apply
```

对账规则：`审听结果=通过` 会校验并归档 `temp/<歌曲ID>/`，然后保留飞书记录；
`审听结果=废弃/淘汰`（或 `生成状态` 为废弃/淘汰）会删除对应临时目录和飞书记录。
其他状态保持不变。资源库中已经完整归档的正式资产不会因自动对账被删除。

按使用场景分类资源库歌曲：

```bash
python -m scripts.classify_library --sync-feishu --apply
```

分类字段“使用场景”支持多选，当前选项为：睡前/助眠、跑步/运动、通勤/坐车、学习/专注、工作/办公、冥想/放松、阅读/咖啡馆、旅行/风景、短视频BGM、聚会/氛围。“音乐方向”继续表示曲风；新歌的 `manifest.json` 用 `usage_scenes` 保存场景，显式标签优先于关键词推断。

准备 Apple Music / 发行商上传包：

```bash
python -m scripts.prepare_release \
  --song-dir resource_library/SONG-YYYYMMDD-001
```

脚本会在歌曲目录下生成 `release/audio_apple_24bit.wav`、`release/cover_3000.jpg`、
`release/release_metadata.json` 和 `release/release_metadata.csv`，并把常见标签写入 WAV。
发行商的元数据表仍是权威来源；ISRC、UPC 等编号由发行商分配，脚本不会伪造。
歌名、艺人、表演者、作曲、作词、制作人和版权信息优先读取 manifest 的 `credits`；
缺少的作者字段会明确留空，不会擅自把 AI 或用户写成作者。

`comfy_submit` 会把 prompt 状态写入下载目录的 `comfy_state.json`，重复执行会恢复或复用同一任务；
默认使用 `.ai_music_pipeline.lock` 防止并发提交。只有明确需要重新生成时才使用 `--force`。
`prepare_release` 对相同输入会复用已有发行包；需要重建时使用 `--force`。翻唱、非商用或短于 30 秒的内容默认不会进入发行包。

运行安全测试：

```bash
python3 -m unittest discover -s tests -v
```

生成发行包时使用本地资源库中的 FLAC、MP3、封面和 manifest；不会重新依赖 ComfyUI 远端文件。临时目录只有在文件校验成功并完成归档后才会删除。

生成新媒体全曲视频：

```bash
python -m scripts.prepare_video \
  --song-dir resource_library/SONG-YYYYMMDD-001 \
  --source resource_library/SONG-YYYYMMDD-001/video_loop_source_864x480.mp4
```

脚本会把循环源片段自动铺满歌曲时长，接入本地 `audio_320k.mp3`，输出
`video_music_1920x1080.mp4`，并把视频信息写回歌曲的 `manifest.json`。输出采用临时文件
完成后原子替换，避免中断留下损坏的 MP4；需要重建时使用 `--force`。竖版或方形版本
使用 `--width 1080 --height 1920` 或 `--width 1080 --height 1080`。

飞书 Base 中的“新媒体视频”表单独管理视频版本和各平台发布状态；同一首歌可以有多条
横版、竖版、短版记录，不与“发布数据表”的流媒体发行状态混在一起。

按飞书审听结果自动生产视频：

```bash
python -m scripts.run_video_automation --config config.json
python -m scripts.run_video_automation --config config.json --apply
```

第一条只预览队列；第二条执行完整流程。仅 `审听结果=通过` 且缺少有效 1080p 成品的歌曲
会进入队列。流程使用 Flux 生成 1344×768 电影感关键帧，再通过 MiniMax H3 官方 FL2VA
提示词结构、首尾同帧和 8-step Turbo 生成约 12.25 秒循环源，最后接入本地原曲并登记
“新媒体视频”表。ComfyUI 离线时会写入等待状态并在下一次调度重试；已完成歌曲按本地
文件校验和飞书歌曲 ID 幂等跳过。

明确需要重做某一首已有视频时，必须同时指定歌曲，避免误伤整个资源库：

```bash
python -m scripts.run_video_automation --config config.json \
  --song-id SONG-YYYYMMDD-001 --preset mountain_pavilion --force --apply
```

macOS 定时配置在 `launchd/cn.sunguochao.ai-music-video.plist`。主任务每天 10:30 运行，
12:30、15:30、19:30、22:30 只负责补偿重试；没有待处理歌曲时立即退出。

## 版权

使用 MiniMax Music 3 生成的作品按项目要求保留 `MiniMax-Music3` 商用标注。不得将他人词曲翻唱记录标记为原创或可商用。
