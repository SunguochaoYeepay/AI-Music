from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class VisualPreset:
    name: str
    keyframe_prompt: str
    scene_description: str
    motion_description: str


COMMON_FINISH = (
    " Rich visual depth, elegant negative space, realistic materials, subtle volumetric atmosphere, "
    "natural exposure, high-end cinematography, 35mm lens, eye-level static camera, detailed but "
    "uncluttered. No person, no text, no logo, no watermark, no illustration, no anime, no "
    "oversaturated colors, no extreme blur."
)


PRESETS = {
    "mountain_pavilion": VisualPreset(
        "mountain_pavilion",
        "A premium cinematic still for a beloved uplifting healing instrumental music video, wide "
        "16:9 composition. An open-sided contemporary timber pavilion rests quietly above layered "
        "emerald mountains at early sunrise. A sea of luminous white clouds fills the valleys below; "
        "soft golden light enters from the right and brushes a dark walnut floor. One sheer linen "
        "curtain hangs near a slender wooden column, a small low tea table holds a matte ceramic cup, "
        "and delicate maple leaves frame the upper left. Sophisticated Japanese-modern architecture, "
        "peaceful but gently hopeful, restrained jade green, pearl white, charcoal and warm gold." + COMMON_FINISH,
        "an open timber mountain pavilion above layered emerald peaks and a luminous sea of clouds, "
        "with a sheer linen curtain, a low tea table, a ceramic cup, delicate maple leaves, and soft "
        "golden sunrise light",
        "The cloud sea flows almost imperceptibly through the valleys; the sheer curtain and finest "
        "maple leaves breathe in a gentle breeze; thin high clouds drift slowly and narrow bands of "
        "sunlight move subtly across the walnut floor before returning",
    ),
    "rainy_room": VisualPreset(
        "rainy_room",
        "A premium cinematic still for a calming instrumental music video, wide 16:9 composition. "
        "A quiet apartment after rain, viewed toward a floor-to-ceiling window. Crisp raindrops and "
        "thin water trails cover the glass. Beyond it, a modern city glows in deep teal and cobalt "
        "beneath layered clouds. A small amber lamp lights a dark walnut desk, a ceramic cup and a "
        "delicate potted plant, creating refined cool-blue and warm-amber contrast." + COMMON_FINISH,
        "a rain-covered floor-to-ceiling window, a softly glowing blue city, layered storm clouds, "
        "and a warm amber lamp illuminating a walnut desk, ceramic cup, and delicate potted plant",
        "Raindrops slide down the glass at varied slow speeds and occasionally merge; distant clouds "
        "drift gently and city lights shimmer through wet glass; the plant's finest leaves sway by a "
        "few millimeters and the lamp reflection subtly lengthens, then returns",
    ),
    "neon_city": VisualPreset(
        "neon_city",
        "A premium cinematic still for an elegant city-pop instrumental music video, wide 16:9 "
        "composition. An empty elevated urban street at blue hour after a light rain, framed from a "
        "quiet covered walkway. Wet asphalt mirrors restrained coral, cyan and warm shop-window "
        "lights. A cream-colored late-1980s tram waits in the middle distance beneath thin overhead "
        "wires; glass towers and small trees recede into atmospheric depth. Sophisticated retro-modern "
        "Tokyo mood without readable signs, balanced cool dusk and warm interior light." + COMMON_FINISH,
        "an empty rain-polished city street at blue hour, a cream vintage tram, restrained neon "
        "reflections, glass towers, small trees, and a quiet covered walkway",
        "Fine mist drifts slowly across the distant street; tram interior lights breathe almost "
        "imperceptibly; small tree leaves flutter gently; reflections ripple in shallow puddles and "
        "thin clouds move across the blue-hour sky",
    ),
    "dawn_path": VisualPreset(
        "dawn_path",
        "A premium cinematic still for an uplifting running instrumental music video, wide 16:9 "
        "composition. A graceful riverside path curves through dew-covered silver grass at sunrise. "
        "Low coral sunlight passes between tall green trees and creates long soft shadows across the "
        "empty path. The river catches pale gold highlights; a clean modern skyline sits far on the "
        "horizon under layered lavender and blue clouds. Fresh, energetic and refined rather than "
        "sports-advertising imagery." + COMMON_FINISH,
        "an empty curving riverside path, dew-covered silver grass, tall green trees, a softly glowing "
        "river, distant skyline, and layered sunrise clouds",
        "Grass tips and fine leaves move in a gentle rhythmic breeze; tiny dew highlights flicker; "
        "thin clouds glide slowly above the skyline and subtle light ripples travel across the river",
    ),
    "quiet_library": VisualPreset(
        "quiet_library",
        "A premium cinematic still for a contemplative instrumental music video, wide 16:9 "
        "composition. A quiet contemporary library reading room at dusk, with tall dark wood shelves, "
        "a single walnut table, an amber reading lamp and an open book. A large side window reveals "
        "soft blue clouds and slender tree branches. Restrained forest green, charcoal, amber and "
        "silver-blue palette; calm, intimate and sophisticated." + COMMON_FINISH,
        "a quiet dark-wood library, an amber reading lamp, an open book, a large dusk window, soft "
        "blue clouds, and slender tree branches",
        "Tree branches sway subtly beyond the window; thin clouds drift; a page corner lifts and "
        "settles by a few millimeters while the warm lamp reflection changes almost imperceptibly",
    ),
}


def get_preset(name: str) -> VisualPreset:
    try:
        return PRESETS[name]
    except KeyError as error:
        raise ValueError(f"Unknown visual preset: {name}") from error


def stable_seed(song_id: str, offset: int = 0) -> int:
    digest = hashlib.sha256(song_id.encode("utf-8")).digest()
    return (int.from_bytes(digest[:8], "big") + offset) % (2**63 - 1)


def choose_preset(fields: dict[str, Any]) -> VisualPreset:
    text = " ".join(str(value) for value in fields.values()).casefold()
    if any(term in text for term in ("跑步", "晨跑", "运动", "动力", "sunrise", "running")):
        return PRESETS["dawn_path"]
    if any(term in text for term in ("城市", "霓虹", "通勤", "晚风", "city", "neon")):
        return PRESETS["neon_city"]
    if any(term in text for term in ("雨", "夜", "睡眠", "冥想", "疗愈", "rain", "nocturnal")):
        return PRESETS["rainy_room"]
    return PRESETS["quiet_library"]


def build_flux_workflow(song_id: str, preset: VisualPreset) -> dict[str, Any]:
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "flux1-dev.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "DualCLIPLoader", "inputs": {"clip_name1": "clip_l.safetensors", "clip_name2": "t5xxl_fp8_e4m3fn.safetensors", "type": "flux", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": preset.keyframe_prompt}},
        "5": {"class_type": "FluxGuidance", "inputs": {"conditioning": ["4", 0], "guidance": 3.5}},
        "6": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["5", 0]}},
        "7": {"class_type": "EmptySD3LatentImage", "inputs": {"width": 1344, "height": 768, "batch_size": 1}},
        "8": {"class_type": "KSampler", "inputs": {"model": ["1", 0], "positive": ["5", 0], "negative": ["6", 0], "latent_image": ["7", 0], "seed": stable_seed(song_id), "steps": 24, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
        "10": {"class_type": "SaveImage", "inputs": {"images": ["9", 0], "filename_prefix": f"image/{song_id}-video-keyframe"}},
    }


def h3_prompt(preset: VisualPreset) -> str:
    return (
        "How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns "
        "with the 0.00-second mark of the target video; Picture 2 (from Shot 1) aligns with the "
        "12.25-second mark of the target video.\n\n"
        f"integrated_multimodal_description: [Shot 1] Live-action, cinematic, a wide static shot "
        f"begins in the exact framing established by Picture 1: {preset.scene_description}. The "
        f"camera holds a Static Shot throughout. {preset.motion_description}. During the final four "
        "seconds, cloud positions, moving details, light intensity, reflections, and object positions "
        "progressively converge to the exact composition, lighting, colors, and object positions "
        "established by Picture 2 at 12.25 seconds. No new objects, no people, no cuts, no camera "
        "movement, no scale change, no text, no logo, and no watermark.\n\n"
        "overall_soundscape: N/A\n\nnon_diegetic_music: N/A"
    )


def build_h3_workflow(song_id: str, uploaded_keyframe: str, preset: VisualPreset) -> dict[str, Any]:
    return {
        "3": {"class_type": "UNETLoader", "inputs": {"unet_name": "h3\\minimax_h3_fl2va_pruned_int8_convrot.safetensors", "weight_dtype": "default"}},
        "20": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["3", 0], "lora_name": "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors", "strength_model": 1.0}},
        "4": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors", "type": "minimax", "device": "default"}},
        "5": {"class_type": "VAELoader", "inputs": {"vae_name": "h3\\minimax_h3_video_vae_fp16.safetensors"}},
        "7": {"class_type": "LoadImage", "inputs": {"image": uploaded_keyframe, "upload": "image"}},
        "8": {"class_type": "MiniMaxH3ImageToVideo", "inputs": {"clip": ["4", 0], "vae": ["5", 0], "prompt": h3_prompt(preset), "width": 1344, "height": 768, "length": 294, "first_frame": ["7", 0], "last_frame": ["7", 0]}},
        "9": {"class_type": "BasicGuider", "inputs": {"model": ["20", 0], "conditioning": ["8", 0]}},
        "10": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "res_multistep"}},
        "11": {"class_type": "BasicScheduler", "inputs": {"model": ["20", 0], "scheduler": "simple", "steps": 8, "denoise": 1.0}},
        "12": {"class_type": "RandomNoise", "inputs": {"noise_seed": stable_seed(song_id, 1)}},
        "13": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["12", 0], "guider": ["9", 0], "sampler": ["10", 0], "sigmas": ["11", 0], "latent_image": ["8", 1]}},
        "14": {"class_type": "VAEDecode", "inputs": {"samples": ["13", 0], "vae": ["5", 0]}},
        "18": {"class_type": "CreateVideo", "inputs": {"images": ["14", 0], "fps": 24.0, "bit_depth": 8}},
        "19": {"class_type": "SaveVideo", "inputs": {"video": ["18", 0], "filename_prefix": f"video/{song_id}-H3-loop-turbo8", "format": "mp4", "codec": "auto"}},
    }
