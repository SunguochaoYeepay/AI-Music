# AI Music Pipeline

将 MiniMax Music 3、Flux、ComfyUI 和飞书多维表格串成可迁移的音乐生产流程。

## 设计原则

- ComfyUI 负责生成，脚本负责提交、轮询、下载和校验。
- 本地资源库是音频和封面的长期资产来源，远端 URL 只作为生成源记录。
- 飞书 CLI 负责元数据同步，浏览器只用于人工确认。
- 不自动对外发布；发布前保留人工审批。
- 不把令牌、密码、个人绝对路径或媒体大文件提交到 Git。

## 目录

```text
ai_music_pipeline/       可复用的 Python 模块
scripts/                  命令行入口
config.example.json       配置模板，不含凭证
resource_library/         本地媒体资产（被 Git 忽略）
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
python -m scripts.comfy_submit --workflow workflow.json --wait --download-dir output
```

将一条歌曲记录写入飞书：

```bash
python -m scripts.sync_feishu --record record.json --table-id <table-id>
```

生成发行包时使用本地资源库中的 FLAC、MP3、封面和 manifest；不会重新依赖 ComfyUI 远端文件。

## 版权

使用 MiniMax Music 3 生成的作品按项目要求保留 `MiniMax-Music3` 商用标注。不得将他人词曲翻唱记录标记为原创或可商用。
