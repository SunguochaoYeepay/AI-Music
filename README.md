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

复制配置模板后按本机环境修改：

```bash
cp config.example.json config.json
```

## 常用操作

提交一个已经展开为 API 格式的 ComfyUI workflow：

```bash
python -m scripts.comfy_submit --workflow workflow.json --wait --download-dir temp/SONG-YYYYMMDD-001

归档完成后清理临时目录：

```bash
python -m scripts.archive_assets \
  --temp-dir temp/SONG-YYYYMMDD-001 \
  --resource-dir resource_library/SONG-YYYYMMDD-001 \
  audio_master.flac audio_320k.mp3 cover_1024.png manifest.json
```
```

将一条歌曲记录写入飞书：

```bash
python -m scripts.sync_feishu --record record.json --table-id <table-id>
```

按审核结果对账（默认只预览）：

```bash
python -m scripts.reconcile_reviews --table-id <table-id>
python -m scripts.reconcile_reviews --table-id <table-id> --apply
```

对账规则：`审听结果=通过` 会校验并归档 `temp/<歌曲ID>/`，然后保留飞书记录；
`审听结果=废弃/淘汰`（或 `生成状态` 为废弃/淘汰）会删除对应临时目录和飞书记录。
其他状态保持不变。资源库中已经完整归档的正式资产不会因自动对账被删除。

准备 Apple Music / 发行商上传包：

```bash
python -m scripts.prepare_release \
  --song-dir resource_library/SONG-YYYYMMDD-001
```

脚本会在歌曲目录下生成 `release/audio_apple_24bit.wav`、
`release/release_metadata.json` 和 `release/release_metadata.csv`，并把常见标签写入 WAV。
发行商的元数据表仍是权威来源；ISRC、UPC 等编号由发行商分配，脚本不会伪造。
歌名、艺人、表演者、作曲、作词、制作人和版权信息优先读取 manifest 的 `credits`；
缺少的作者字段会明确留空，不会擅自把 AI 或用户写成作者。

生成发行包时使用本地资源库中的 FLAC、MP3、封面和 manifest；不会重新依赖 ComfyUI 远端文件。临时目录只有在文件校验成功并完成归档后才会删除。

## 版权

使用 MiniMax Music 3 生成的作品按项目要求保留 `MiniMax-Music3` 商用标注。不得将他人词曲翻唱记录标记为原创或可商用。
