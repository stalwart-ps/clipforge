from app.core.schemas import APISchema


class GPUInfo(APISchema):
    has_gpu: bool = False
    gpu_name: str | None = None
    driver_version: str | None = None
    cuda_version: str | None = None
    vram_total_mb: int | None = None
    vram_used_mb: int | None = None
    vram_free_mb: int | None = None
    temperature_c: int | None = None
    gpu_utilization_percent: int | None = None
    status: str = "not_detected"  # optimal, high_usage, not_detected, error


class FFmpegInfo(APISchema):
    is_installed: bool = False
    version: str | None = None
    has_libx264: bool = False
    has_h264_nvenc: bool = False
    has_hevc_nvenc: bool = False
    has_libass: bool = False
    status: str = "missing"  # ready, ready_cpu_only, missing


class OllamaModel(APISchema):
    name: str
    size_bytes: int | None = None
    parameter_size: str | None = None
    modified_at: str | None = None


class OllamaInfo(APISchema):
    is_reachable: bool = False
    url: str
    models: list[OllamaModel] = []
    status: str = "disconnected"  # connected, disconnected, empty


class YtDlpInfo(APISchema):
    is_installed: bool = False
    version: str | None = None
    has_js_runtime: bool = False
    js_runtime_type: str | None = None  # deno, node, none
    js_runtime_version: str | None = None
    status: str = "missing"  # ready, warning_no_js, missing


class SystemDiagnosticsResponse(APISchema):
    gpu: GPUInfo
    ffmpeg: FFmpegInfo
    ollama: OllamaInfo
    ytdlp: YtDlpInfo
    recommended_preset: str  # lite, balanced, pro
    timestamp: str


class YtDlpUpdateResponse(APISchema):
    success: bool
    old_version: str | None = None
    new_version: str | None = None
    output: str
