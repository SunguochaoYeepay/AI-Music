from __future__ import annotations

from typing import Any


SCENE_OPTIONS = (
    "睡前/助眠",
    "跑步/运动",
    "通勤/坐车",
    "学习/专注",
    "工作/办公",
    "冥想/放松",
    "阅读/咖啡馆",
    "旅行/风景",
    "短视频BGM",
    "聚会/氛围",
)

_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("睡前/助眠", ("睡眠", "睡前", "失眠", "夜晚", "晚安", "nocturnal", "sleep", "bedtime")),
    ("跑步/运动", ("跑步", "运动", "健身", "workout", "running", "energetic")),
    ("通勤/坐车", ("通勤", "坐车", "驾车", "drive", "commute", "road", "sunrise drive")),
    ("学习/专注", ("学习", "专注", "focused", "study", "concentration")),
    ("工作/办公", ("工作", "办公", "focused work", "office", "productivity")),
    ("冥想/放松", ("冥想", "放松", "疗愈", "平静", "calm", "healing", "relax")),
    ("阅读/咖啡馆", ("阅读", "咖啡", "reading", "cafe", "rainy window")),
    ("旅行/风景", ("旅行", "风景", "日出", "sunrise", "landscape", "journey")),
    ("短视频BGM", ("短视频", "BGM", "reels", "short video")),
    ("聚会/氛围", ("聚会", "派对", "party", "social", "dancefloor")),
)


def _flatten(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return " ".join(_flatten(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return " ".join(_flatten(item) for item in value)
    return str(value)


def classify_manifest(manifest: dict[str, Any]) -> list[str]:
    """Return stable usage scenes, preserving explicit manual classifications."""
    explicit = manifest.get("usage_scenes")
    if isinstance(explicit, list):
        selected = [str(item) for item in explicit if str(item) in SCENE_OPTIONS]
        if selected:
            return list(dict.fromkeys(selected))

    text = _flatten(manifest).casefold()
    selected = [scene for scene, keywords in _RULES if any(keyword.casefold() in text for keyword in keywords)]
    return selected or ["阅读/咖啡馆"]
