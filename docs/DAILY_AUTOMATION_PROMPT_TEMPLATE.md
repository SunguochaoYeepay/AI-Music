# 每日 AI 音乐自动化提示词模板

创建家里电脑的 Codex 每日任务前，先替换这些占位符：

- `<PERSONAL_WIKI_URL>`：个人飞书 Wiki URL
- `<PERSONAL_BASE_TOKEN>`：个人 Wiki 对应 Base token
- `<TREND_TABLE_ID>`：趋势雷达表 ID
- `<MUSIC_TABLE_ID>`：音乐生产表 ID
- `<HOTSPOT_BASE_URL>`：另一个 AI 维护的新媒体热点库 URL
- `<HOTSPOT_BASE_TOKEN>`：热点库 Base token
- `<HOTSPOT_TABLE_ID>`：热点库表 ID
- `<COMFYUI_URL>`：家里电脑建议使用 `http://127.0.0.1:8188`

不要把替换后含个人标识的版本提交到公开 GitHub。

---

每天上午整理最新音乐偏好和内容趋势，优先关注抖音、小红书、B站及音乐平台公开信息。把 `<HOTSPOT_BASE_URL>`（Base token `<HOTSPOT_BASE_TOKEN>`，表 `<HOTSPOT_TABLE_ID>`）作为只读上游来源，由另一个 AI 负责更新；本任务必须读取全部分页，严禁新增、修改或删除源表记录。优先读取最新 1-2 天，综合排名、热度值、是否精选和题材；“短剧相关性”不得直接等同于音乐适配度。灾害、死亡、犯罪、军事、争议人物及敏感新闻自动排除；影视、游戏、角色、艺人和现有歌曲热点只能提取抽象情绪、场景和节奏，不得直接改编或模仿。

将有证据的候选方向写入个人飞书 Wiki `<PERSONAL_WIKI_URL>` 的趋势雷达表 `<TREND_TABLE_ID>`。每日同时核验今天、明天和未来 7 天的节日、节气、纪念日及季节节点；记录准确日期、地区、类型、场景、提前量、可靠来源和核验日期。无法核实或已过期的节点不得生成。每天至少 3 首中默认最多 1 首来自日历方向。

每日增加一个公版经典研究候选。必须记录作品、词曲作者、作者去世年份或首次发表年份、拟发行地区、词曲判断、权威证据和核验日期，并区分作品、编曲和录音版权。证据不足统一标记“需授权/仅研究”，不得自动生成；不得使用他人录音或采样。

每天 10:30 使用项目锁，先对个人飞书音乐生产表 `<MUSIC_TABLE_ID>` 执行：

```powershell
python -m scripts.reconcile_reviews --base-token <PERSONAL_BASE_TOKEN> --table-id <MUSIC_TABLE_ID> --apply
```

记录分页时必须停止并报告。审听通过时，校验并归档资产，生成或复用发行包；废弃或淘汰时先删除飞书记录，再清理该歌曲 ID 的临时目录。已归档正式资产不得自动删除。作曲、作词、出版者缺失时保持空白；不得伪造 ISRC、UPC。翻唱、非商用或短于 30 秒的内容不得生成发行包。

然后检查家里 ComfyUI `<COMFYUI_URL>`。在线时，基于当天入选趋势顺序生成至少 3 首不同趋势或不同场景/曲风的原创候选。默认男声艺人为燧燧，女声为念念；不得模仿具体艺人或歌曲。

每首必须使用不同歌曲 ID、独立 `temp/<歌曲ID>/`、独立 workflow 和 state 文件。优先恢复已有 prompt ID，禁止超时后重复提交。每首同时保存 FLAC 和 320k MP3并检查时长；短于 30 秒应调整段落结构或种子重试，仍失败则记录并报告。

封面使用 1024×1024 Flux 专用采样链：`UNETLoader -> ModelSamplingFlux`，正向 conditioning 经 `FluxGuidance`，再接 `BasicGuider`、`KSamplerSelect`、`BasicScheduler` 和 `SamplerCustomAdvanced`。禁止把 Flux UNET 直接接普通 `KSampler`。必须视觉检查清晰度、黑图、伪文字、水印和构图；不合格必须重做。

所有中间文件只写入 `temp/<歌曲ID>/`。只有 FLAC、320k MP3、封面和 manifest 全部校验成功后，才原子归档到 `resource_library/<歌曲ID>/` 并删除对应临时目录。归档后同步个人飞书音乐生产表，状态设为待审听，并执行：

```powershell
python -m scripts.classify_library --song-dir resource_library/<歌曲ID> --base-token <PERSONAL_BASE_TOKEN> --table-id <MUSIC_TABLE_ID> --sync-feishu --apply
```

使用场景可多选：睡前/助眠、跑步/运动、通勤/坐车、学习/专注、工作/办公、冥想/放松、阅读/咖啡馆、旅行/风景、短视频BGM、聚会/氛围。音乐方向表示曲风。

ComfyUI 离线时只记录趋势和跳过原因，不重复提交。只允许使用个人飞书账号和个人 Wiki，严禁使用易宝支付相关账号或数据。不要自动发布到任何外部平台，所有发布留给用户确认。
