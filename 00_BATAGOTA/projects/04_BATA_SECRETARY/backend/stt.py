import os
import re
import shutil
import struct
import subprocess
import tempfile
import time
from urllib.parse import parse_qs, urlparse
import wave
from threading import Lock
from typing import Any, Callable, Dict, Optional

from faster_whisper import WhisperModel

try:
    from youtube_transcript_api import YouTubeTranscriptApi
except Exception:
    YouTubeTranscriptApi = None

_STREAM_MODEL = None
_UPLOAD_MODEL = None
_STREAM_MODEL_LOCK = Lock()
_UPLOAD_MODEL_LOCK = Lock()


class SubtitleProbeError(RuntimeError):
    def __init__(self, message: str, *, transient: bool = False):
        super().__init__(message)
        self.transient = transient


def _get_stream_model() -> WhisperModel:
    global _STREAM_MODEL
    if _STREAM_MODEL is None:
        with _STREAM_MODEL_LOCK:
            if _STREAM_MODEL is None:
                model_size = os.getenv("WHISPER_STREAM_MODEL_SIZE", "base")
                compute_type = os.getenv("WHISPER_STREAM_COMPUTE_TYPE", os.getenv("WHISPER_COMPUTE_TYPE", "int8"))
                _STREAM_MODEL = WhisperModel(model_size, device="cpu", compute_type=compute_type)
    return _STREAM_MODEL


def _get_upload_model() -> WhisperModel:
    global _UPLOAD_MODEL
    if _UPLOAD_MODEL is None:
        with _UPLOAD_MODEL_LOCK:
            if _UPLOAD_MODEL is None:
                model_size = os.getenv("WHISPER_UPLOAD_MODEL_SIZE", os.getenv("WHISPER_MODEL_SIZE", "base"))
                compute_type = os.getenv("WHISPER_UPLOAD_COMPUTE_TYPE", os.getenv("WHISPER_COMPUTE_TYPE", "int8"))
                _UPLOAD_MODEL = WhisperModel(model_size, device="cpu", compute_type=compute_type)
    return _UPLOAD_MODEL


def _normalize_audio_suffix(audio_format: Optional[str]) -> str:
    value = (audio_format or "webm").strip().lower()
    if "/" in value:
        value = value.split("/", 1)[1]
    if ";" in value:
        value = value.split(";", 1)[0]
    mapping = {
        "x-wav": "wav",
        "wave": "wav",
        "mpeg": "mp3",
    }
    value = mapping.get(value, value)
    if not value:
        value = "webm"
    return "." + value


def _get_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
        return value if value > 0 else default
    except ValueError:
        return default


def _get_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}


def _get_float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
        return value if value >= 0 else default
    except ValueError:
        return default


def _is_generic_text(text: str) -> bool:
    """Placeholder나 generic text는 무시 (Whisper 환각)."""
    if not text:
        return True
    generic = {
        "한국어 대화",
        "자연스러운 한국어 대화",
        "음성",
        "음성입니다",
        "말합니다",
        "말씀합니다",
        "이야기",
        "이야기합니다",
        "대화",
        "대화합니다",
    }
    return text.strip() in generic


def _postprocess_transcript(transcript: str) -> str:
    """Whisper 환각 패턴(예: '한국어 대화' 반복)을 최소 후처리로 제거."""
    if not transcript:
        return ""

    text = transcript.strip()
    lowered = text.lower()

    # '한국어 대화' 계열 반복 문구는 실질 내용이 없는 환각으로 간주
    if _is_generic_text(text):
        return ""
    if re.fullmatch(r"(?:한국어\s*대화\s*){2,}", text):
        return ""

    # 문장 중간에 섞인 환각 토큰 제거
    text = re.sub(r"\b한국어\s*대화\b", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    # 안전장치: '대화' 관련 토큰만 남는 경우 제거
    tokens = re.findall(r"[\w가-힣]+", lowered)
    if tokens and all(t in {"한국어", "대화"} for t in tokens):
        return ""

    return text


def _is_silent_wav(wav_path: str, threshold: float = 20.0) -> bool:
    """WAV 파일의 RMS 에너지가 threshold 미만이면 무음으로 판단.
    
    기본값 20: 한국어 일상 대화 기준
    - 빠른 음성도 인식 가능하도록 매우 낮춤
    - RMS < 20 = 실제 무음/백그라운드 노이즈만
    """
    try:
        with wave.open(wav_path, "rb") as wf:
            n_frames = wf.getnframes()
            if n_frames == 0:
                return True
            raw = wf.readframes(n_frames)
            sampwidth = wf.getsampwidth()
            if sampwidth == 2:
                fmt = f"<{len(raw) // 2}h"
                samples = struct.unpack(fmt, raw)
                rms = (sum(s * s for s in samples) / len(samples)) ** 0.5
                return rms < threshold
    except Exception:
        pass
    return False


def _is_invalid_or_silent_wav(
    wav_path: str,
    *,
    rms_threshold: float = 12.0,
    peak_threshold: int = 64,
    min_frames: int = 1600,
) -> bool:
    """WAV가 무음/비정상(프레임 부족, 거의 0 신호)인지 확인."""
    try:
        with wave.open(wav_path, "rb") as wf:
            n_frames = wf.getnframes()
            if n_frames < min_frames:
                return True

            sampwidth = wf.getsampwidth()
            if sampwidth != 2:
                return False

            raw = wf.readframes(n_frames)
            if not raw:
                return True

            fmt = f"<{len(raw) // 2}h"
            samples = struct.unpack(fmt, raw)
            if not samples:
                return True

            sum_sq = 0.0
            peak = 0
            for s in samples:
                v = abs(s)
                if v > peak:
                    peak = v
                sum_sq += float(s) * float(s)

            rms = (sum_sq / len(samples)) ** 0.5
            return rms < rms_threshold or peak < peak_threshold
    except Exception:
        return False


def _normalize_profile(stt_profile: Optional[str]) -> str:
    value = (stt_profile or "normal").strip().lower()
    if value in {"high", "normal", "fast"}:
        return value
    return "normal"


def _stream_profile_options(stt_profile: Optional[str]) -> dict:
    profile = _normalize_profile(stt_profile)

    if profile == "high":
        return {
            "beam_size": _get_int_env("WHISPER_STREAM_HIGH_BEAM_SIZE", 8),
            "vad_filter": _get_bool_env("WHISPER_STREAM_HIGH_VAD_FILTER", False),
            "condition_on_previous_text": _get_bool_env("WHISPER_STREAM_HIGH_CONDITION_ON_PREVIOUS_TEXT", False),
            "use_initial_prompt": _get_bool_env("WHISPER_STREAM_HIGH_USE_INITIAL_PROMPT", False),
            "without_timestamps": _get_bool_env("WHISPER_STREAM_HIGH_WITHOUT_TIMESTAMPS", True),
        }

    if profile == "fast":
        return {
            "beam_size": _get_int_env("WHISPER_STREAM_FAST_BEAM_SIZE", 2),
            "vad_filter": _get_bool_env("WHISPER_STREAM_FAST_VAD_FILTER", True),
            "condition_on_previous_text": _get_bool_env("WHISPER_STREAM_FAST_CONDITION_ON_PREVIOUS_TEXT", False),
            "use_initial_prompt": _get_bool_env("WHISPER_STREAM_FAST_USE_INITIAL_PROMPT", False),
            "without_timestamps": _get_bool_env("WHISPER_STREAM_FAST_WITHOUT_TIMESTAMPS", True),
        }

    return {
        "beam_size": _get_int_env("WHISPER_STREAM_BEAM_SIZE", 4),
        "vad_filter": _get_bool_env("WHISPER_STREAM_VAD_FILTER", False),
        "condition_on_previous_text": _get_bool_env("WHISPER_STREAM_CONDITION_ON_PREVIOUS_TEXT", False),
        "use_initial_prompt": _get_bool_env("WHISPER_STREAM_USE_INITIAL_PROMPT", False),
        "without_timestamps": _get_bool_env("WHISPER_STREAM_WITHOUT_TIMESTAMPS", True),
    }


def _upload_profile_options(stt_profile: Optional[str]) -> dict:
    profile = _normalize_profile(stt_profile)

    if profile == "high":
        return {
            "beam_size": _get_int_env("WHISPER_UPLOAD_HIGH_BEAM_SIZE", 6),
            "condition_on_previous_text": _get_bool_env("WHISPER_UPLOAD_HIGH_CONDITION_ON_PREVIOUS_TEXT", True),
            "use_initial_prompt": _get_bool_env("WHISPER_UPLOAD_HIGH_USE_INITIAL_PROMPT", False),
            "vad_filter": _get_bool_env("WHISPER_UPLOAD_HIGH_VAD_FILTER", False),
        }

    if profile == "fast":
        return {
            "beam_size": _get_int_env("WHISPER_UPLOAD_FAST_BEAM_SIZE", 2),
            "condition_on_previous_text": _get_bool_env("WHISPER_UPLOAD_FAST_CONDITION_ON_PREVIOUS_TEXT", False),
            "use_initial_prompt": _get_bool_env("WHISPER_UPLOAD_FAST_USE_INITIAL_PROMPT", False),
            "vad_filter": _get_bool_env("WHISPER_UPLOAD_FAST_VAD_FILTER", False),
        }

    return {
        "beam_size": _get_int_env("WHISPER_UPLOAD_BEAM_SIZE", 4),
        "condition_on_previous_text": True,
        "use_initial_prompt": False,
        "vad_filter": False,
    }


def _transcribe_file(
    audio_bytes: bytes,
    chunk_index: int,
    audio_format: Optional[str],
    language: Optional[str],
    *,
    model: WhisperModel,
    vad_filter: bool,
    beam_size: int,
    condition_on_previous_text: bool,
    use_initial_prompt: bool,
    without_timestamps: bool,
) -> str:
    if not audio_bytes:
        return ""

    temp_path = None
    converted_path = None

    try:
        suffix = _normalize_audio_suffix(audio_format)
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            temp_file.write(audio_bytes)
            temp_path = temp_file.name

        source_path = temp_path
        
        # WebM/OPUS 같은 압축 형식은 afconvert로 WAV로 변환
        suffix_clean = suffix.lstrip(".")
        if shutil.which("afconvert") and suffix_clean in {"webm", "opus", "m4a", "mp4", "mp3"}:
            converted_file = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
            converted_file.close()
            converted_path = converted_file.name
            try:
                subprocess.run(
                    [
                        "afconvert",
                        temp_path,
                        "-f",
                        "WAVE",
                        "-c",
                        "1",
                        "-d",
                        "LEI16@16000",
                        converted_path,
                    ],
                    check=True,
                    capture_output=True,
                )
                source_path = converted_path
            except subprocess.CalledProcessError as e:
                print(f"[WARN] afconvert 변환 실패 (청크 {chunk_index}): {e.stderr.decode('utf-8', errors='ignore')}")
                # 변환 실패해도 원본으로 계속 시도


        if source_path.endswith(".wav"):
            if _is_invalid_or_silent_wav(
                source_path,
                rms_threshold=_get_float_env("WHISPER_STREAM_SILENCE_RMS", 12.0),
                peak_threshold=_get_int_env("WHISPER_STREAM_SILENCE_PEAK", 64),
                min_frames=_get_int_env("WHISPER_STREAM_MIN_FRAMES", 1600),
            ):
                return ""

        language_code = language or os.getenv("WHISPER_LANGUAGE", "ko")
        prompt = None
        segments, _ = model.transcribe(
            source_path,
            language=language_code,
            condition_on_previous_text=condition_on_previous_text,
            initial_prompt=prompt,
            vad_filter=vad_filter,
            beam_size=beam_size,
            without_timestamps=without_timestamps,
        )
        # ───── 필터링 완전 제거 (기본 기능 확인용) ─────────────────────────────────
        transcript = " ".join(segment.text.strip() for segment in segments if segment.text).strip()
        return _postprocess_transcript(transcript)
    except Exception as exc:
        print(f"[WARN] Whisper decode/transcribe error (청크 {chunk_index}): {exc}")
        return ""
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)
        if converted_path and os.path.exists(converted_path):
            os.remove(converted_path)


def _transcribe_pcm_file(
    audio_bytes: bytes,
    chunk_index: int,
    audio_format: Optional[str],
    language: Optional[str],
    stt_profile: Optional[str] = None,
) -> str:
    if not audio_bytes:
        return ""

    options = _upload_profile_options(stt_profile)

    suffix = (_normalize_audio_suffix(audio_format).lstrip(".")).lower()
    if suffix not in {"wav", "wave", "aiff", "aif", "caf", "m4a", "mp4", "mp3", "webm"}:
        return _transcribe_file(
            audio_bytes,
            chunk_index,
            audio_format,
            language,
            model=_get_upload_model(),
            vad_filter=options["vad_filter"],
            beam_size=options["beam_size"],
            condition_on_previous_text=options["condition_on_previous_text"],
            use_initial_prompt=options["use_initial_prompt"],
            without_timestamps=False,
        )

    temp_path = None
    converted_path = None

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{suffix}") as temp_file:
            temp_file.write(audio_bytes)
            temp_path = temp_file.name

        source_path = temp_path
        if shutil.which("afconvert") and suffix in {"aiff", "aif", "caf", "m4a", "mp4", "mp3"}:
            converted_file = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
            converted_file.close()
            converted_path = converted_file.name
            subprocess.run(
                [
                    "afconvert",
                    temp_path,
                    "-f",
                    "WAVE",
                    "-c",
                    "1",
                    "-d",
                    "LEI16@16000",
                    converted_path,
                ],
                check=True,
                capture_output=True,
            )
            source_path = converted_path


        if source_path.endswith(".wav"):
            if _is_invalid_or_silent_wav(
                source_path,
                rms_threshold=_get_float_env("WHISPER_UPLOAD_SILENCE_RMS", 10.0),
                peak_threshold=_get_int_env("WHISPER_UPLOAD_SILENCE_PEAK", 48),
                min_frames=_get_int_env("WHISPER_UPLOAD_MIN_FRAMES", 2400),
            ):
                return ""

        model = _get_upload_model()
        language_code = language or os.getenv("WHISPER_LANGUAGE", "ko")
        prompt = None
        segments, _ = model.transcribe(
            source_path,
            language=language_code,
            condition_on_previous_text=options["condition_on_previous_text"],
            initial_prompt=prompt,
            vad_filter=options["vad_filter"],
            beam_size=options["beam_size"],
        )
        # ───── 필터링 완전 제거 (기본 기능 확인용) ─────────────────────────────────
        transcript = " ".join(segment.text.strip() for segment in segments if segment.text).strip()
        return _postprocess_transcript(transcript)
    except Exception as exc:
        print(f"[WARN] Whisper full-file error: {exc}")
        return ""
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)
        if converted_path and os.path.exists(converted_path):
            os.remove(converted_path)


def transcribe_audio_bytes(
    audio_bytes: bytes,
    chunk_index: int,
    audio_format: Optional[str] = None,
    language: Optional[str] = None,
    stt_profile: Optional[str] = None,
) -> str:
    options = _stream_profile_options(stt_profile)
    return _transcribe_file(
        audio_bytes,
        chunk_index,
        audio_format,
        language,
        model=_get_stream_model(),
        vad_filter=options["vad_filter"],
        beam_size=options["beam_size"],
        condition_on_previous_text=options["condition_on_previous_text"],
        use_initial_prompt=options["use_initial_prompt"],
        without_timestamps=options["without_timestamps"],
    )


def transcribe_full_audio_bytes(
    audio_bytes: bytes,
    chunk_index: int,
    audio_format: Optional[str] = None,
    language: Optional[str] = None,
    stt_profile: Optional[str] = None,
) -> str:
    return _transcribe_pcm_file(audio_bytes, chunk_index, audio_format, language, stt_profile)


def _strip_subtitle_text(raw_text: str) -> str:
    cleaned_lines = []
    seen = set()

    for line in raw_text.splitlines():
        text = line.strip()
        if not text:
            continue
        if text.upper().startswith("WEBVTT"):
            continue
        if re.match(r"^\d+$", text):
            continue
        if "-->" in text:
            continue

        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"&nbsp;", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            continue

        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned_lines.append(text)

    return " ".join(cleaned_lines).strip()


def _find_best_subtitle_file(tmp_dir: str, language: str) -> Optional[str]:
    subtitle_files = [
        os.path.join(tmp_dir, name)
        for name in os.listdir(tmp_dir)
        if name.lower().endswith((".vtt", ".srt"))
    ]
    if not subtitle_files:
        return None

    language = (language or "ko").lower()

    preferred = [
        path
        for path in subtitle_files
        if f".{language}." in os.path.basename(path).lower()
    ]
    if preferred:
        return sorted(preferred)[0]

    preferred_auto = [
        path
        for path in subtitle_files
        if f".{language}" in os.path.basename(path).lower()
    ]
    if preferred_auto:
        return sorted(preferred_auto)[0]

    return sorted(subtitle_files)[0]


def _is_transient_subtitle_error(stderr: str) -> bool:
    text = (stderr or "").lower()
    markers = [
        "http error 429",
        "too many requests",
        "timed out",
        "temporarily unavailable",
        "unable to download video subtitles",
        "impersonation",
        "po token",
        "requested format is not available",
    ]
    return any(marker in text for marker in markers)


def _extract_video_id(url_or_id: str) -> str:
    value = (url_or_id or "").strip()
    if not value:
        return ""

    if re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
        return value

    parsed = urlparse(value)
    host = (parsed.netloc or "").lower()
    path = (parsed.path or "").strip("/")

    if "youtu.be" in host:
        candidate = path.split("/")[0] if path else ""
        return candidate[:11]

    if "youtube.com" in host:
        query = parse_qs(parsed.query or "")
        if query.get("v"):
            return query["v"][0][:11]
        if path.startswith("shorts/"):
            return path.split("/")[1][:11]
        if path.startswith("embed/"):
            return path.split("/")[1][:11]

    return ""


def _strip_transcript_api_text(items: list) -> str:
    lines = []
    seen = set()
    for item in items:
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        lines.append(text)
    return " ".join(lines).strip()


def _extract_subtitle_text_via_transcript_api(url: str, language: str) -> Dict[str, Any]:
    if YouTubeTranscriptApi is None:
        return {
            "found": False,
            "language": None,
            "subtitle_path": None,
            "transcript": "",
            "status": "api_unavailable",
            "provider": "youtube_transcript_api",
            "items": [],
        }

    video_id = _extract_video_id(url)
    if not video_id:
        return {
            "found": False,
            "language": None,
            "subtitle_path": None,
            "transcript": "",
            "status": "invalid_video_id",
            "provider": "youtube_transcript_api",
            "items": [],
        }

    target = (language or "ko").lower()
    requested_languages = [target, "ko", "ko-KR", "en", "en-US"]

    try:
        items = None
        detected_language = target

        # youtube-transcript-api v1.x
        if hasattr(YouTubeTranscriptApi, "fetch"):
            fetched = YouTubeTranscriptApi().fetch(video_id, languages=requested_languages)
            detected_language = getattr(fetched, "language_code", None) or target
            if hasattr(fetched, "to_raw_data"):
                items = fetched.to_raw_data()
            else:
                snippets = getattr(fetched, "snippets", None)
                if snippets is not None:
                    items = [
                        {
                            "text": getattr(snippet, "text", ""),
                            "start": float(getattr(snippet, "start", 0.0)),
                            "duration": float(getattr(snippet, "duration", 0.0)),
                        }
                        for snippet in snippets
                    ]

        # youtube-transcript-api legacy versions
        if items is None and hasattr(YouTubeTranscriptApi, "get_transcript"):
            items = YouTubeTranscriptApi.get_transcript(video_id, languages=requested_languages)
    except Exception:
        return {
            "found": False,
            "language": None,
            "subtitle_path": None,
            "transcript": "",
            "status": "api_not_found",
            "provider": "youtube_transcript_api",
            "items": [],
        }

    transcript = _strip_transcript_api_text(items)
    if not transcript:
        return {
            "found": False,
            "language": None,
            "subtitle_path": None,
            "transcript": "",
            "status": "empty",
            "provider": "youtube_transcript_api",
            "items": items,
        }

    return {
        "found": True,
        "language": detected_language,
        "subtitle_path": None,
        "transcript": transcript,
        "status": "used",
        "provider": "youtube_transcript_api",
        "items": items,
    }


def _extract_subtitle_text(url: str, language: str, tmp_dir: str) -> Dict[str, Any]:
    out_template = os.path.join(tmp_dir, "caption.%(ext)s")
    cmd = [
        "yt-dlp",
        "--skip-download",
        "--write-sub",
        "--write-auto-sub",
        "--sub-format",
        "vtt/srt/best",
        "--sub-langs",
        f"{language}.*,{language},en.*,en",
        "-o",
        out_template,
        url,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if result.returncode != 0:
        detail = result.stderr.strip()[-500:] or result.stdout.strip()[-500:] or "알 수 없는 오류"
        raise SubtitleProbeError(
            f"자막 조회 실패: {detail}",
            transient=_is_transient_subtitle_error(detail),
        )

    subtitle_path = _find_best_subtitle_file(tmp_dir, language)
    if not subtitle_path or not os.path.exists(subtitle_path):
        return {
            "found": False,
            "language": None,
            "subtitle_path": None,
            "transcript": "",
            "status": "not_found",
        }

    with open(subtitle_path, "r", encoding="utf-8", errors="ignore") as subtitle_file:
        raw_text = subtitle_file.read()

    transcript = _strip_subtitle_text(raw_text)
    if not transcript:
        return {
            "found": False,
            "language": None,
            "subtitle_path": subtitle_path,
            "transcript": "",
            "status": "empty",
        }

    base_name = os.path.basename(subtitle_path).lower()
    language_tag = None
    match = re.search(r"\.([a-z]{2,3}(?:-[a-z]{2,3})?)\.(?:vtt|srt)$", base_name)
    if match:
        language_tag = match.group(1)

    return {
        "found": True,
        "language": language_tag,
        "subtitle_path": subtitle_path,
        "transcript": transcript,
        "status": "used",
    }


def _extract_subtitle_text_with_retry(
    url: str,
    language: str,
    tmp_dir: str,
    progress_callback: Optional[Callable[[str, str], None]] = None,
) -> Dict[str, Any]:
    max_retries = _get_int_env("YOUTUBE_SUBTITLE_PROBE_RETRIES", 2)
    retry_delay_ms = _get_int_env("YOUTUBE_SUBTITLE_PROBE_RETRY_DELAY_MS", 1500)
    attempt = 0
    last_error: Optional[SubtitleProbeError] = None

    while attempt <= max_retries:
        try:
            return _extract_subtitle_text(url, language, tmp_dir)
        except SubtitleProbeError as exc:
            last_error = exc
            if not exc.transient or attempt >= max_retries:
                break
            if progress_callback:
                progress_callback(
                    "subtitle_probe_retry",
                    f"자막 조회 재시도 중 ({attempt + 1}/{max_retries})",
                )
            time.sleep(retry_delay_ms / 1000)
            attempt += 1

    if last_error:
        raise last_error

    raise SubtitleProbeError("자막 조회 실패: 알 수 없는 오류", transient=False)


def _transcribe_youtube_via_asr(
    url: str,
    language: Optional[str],
    stt_profile: Optional[str],
    tmp_dir: str,
    progress_callback: Optional[Callable[[str, str], None]] = None,
) -> Dict[str, Any]:
    has_ffmpeg = bool(shutil.which("ffmpeg"))
    out_template = os.path.join(tmp_dir, "audio.%(ext)s")

    if progress_callback:
        progress_callback("fallback_download", "오디오 다운로드 중")

    if has_ffmpeg:
        cmd = [
            "yt-dlp",
            "--extract-audio",
            "--audio-format",
            "wav",
            "--audio-quality",
            "0",
            "--postprocessor-args",
            "ffmpeg:-ar 16000 -ac 1",
            "-o",
            out_template,
            url,
        ]
    else:
        cmd = [
            "yt-dlp",
            "-f",
            "bestaudio/best",
            "--no-post-overwrites",
            "-o",
            out_template,
            url,
        ]

    download_started = time.monotonic()
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    download_ms = int((time.monotonic() - download_started) * 1000)
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp 오디오 다운로드 오류: {result.stderr.strip()[-400:]}")

    audio_files = [
        os.path.join(tmp_dir, name)
        for name in os.listdir(tmp_dir)
        if not name.startswith(".") and os.path.splitext(name)[1].lower() not in {".vtt", ".srt"}
    ]
    if not audio_files:
        raise RuntimeError("yt-dlp로 오디오를 추출하지 못했습니다.")

    src = sorted(audio_files)[0]
    ext = os.path.splitext(src)[1].lower().lstrip(".")
    wav_path = src

    if ext != "wav":
        if not shutil.which("afconvert"):
            raise RuntimeError("ffmpeg와 afconvert 모두 없어 오디오 변환이 불가합니다. ffmpeg를 설치하세요.")
        if progress_callback:
            progress_callback("fallback_convert", "오디오 변환 중")
        wav_path = os.path.join(tmp_dir, "audio_converted.wav")
        subprocess.run(
            ["afconvert", src, "-f", "WAVE", "-c", "1", "-d", "LEI16@16000", wav_path],
            check=True,
            capture_output=True,
        )

    if progress_callback:
        progress_callback("fallback_transcribe", "Whisper 전사 중")

    transcribe_started = time.monotonic()
    with open(wav_path, "rb") as audio_file:
        audio_bytes = audio_file.read()
    transcript = _transcribe_pcm_file(audio_bytes, 0, "wav", language, stt_profile)
    transcribe_ms = int((time.monotonic() - transcribe_started) * 1000)

    return {
        "transcript": transcript,
        "download_ms": download_ms,
        "transcribe_ms": transcribe_ms,
    }


def transcribe_youtube_url_detailed(
    url: str,
    language: Optional[str] = None,
    stt_profile: Optional[str] = None,
    progress_callback: Optional[Callable[[str, str], None]] = None,
) -> Dict[str, Any]:
    """YouTube URL을 자막 우선으로 처리하고, 없으면 Whisper로 폴백 전사한다."""
    if not shutil.which("yt-dlp"):
        raise RuntimeError("yt-dlp가 설치되어 있지 않습니다. 'pip install yt-dlp'로 설치하세요.")

    language_code = language or os.getenv("WHISPER_LANGUAGE", "ko")
    started = time.monotonic()
    tmp_dir = tempfile.mkdtemp()

    try:
        if progress_callback:
            progress_callback("subtitle_probe", "자막 유무 확인 중")

        subtitle_started = time.monotonic()
        subtitle_result = {
            "found": False,
            "language": None,
            "subtitle_path": None,
            "transcript": "",
            "status": "not_found",
            "provider": None,
            "items": [],
        }

        if progress_callback:
            progress_callback("subtitle_api_probe", "자막 유무 확인 중 (transcript-api)")
        subtitle_result = _extract_subtitle_text_via_transcript_api(url, language_code)

        if not subtitle_result.get("found"):
            if progress_callback:
                progress_callback("subtitle_probe_yt_dlp", "자막 유무 확인 중 (yt-dlp)")
            try:
                if not subtitle_result.get("found"):
                    subtitle_result = _extract_subtitle_text_with_retry(
                        url,
                        language_code,
                        tmp_dir,
                        progress_callback=progress_callback,
                    )
                    subtitle_result["provider"] = "yt_dlp"
            except SubtitleProbeError as exc:
                subtitle_ms = int((time.monotonic() - subtitle_started) * 1000)
                if progress_callback:
                    progress_callback("subtitle_probe_failed", "자막 조회 실패 - 작업 중단")
                raise RuntimeError(
                    f"자막 조회 실패로 중단되었습니다. ({subtitle_ms / 1000:.1f}초) {str(exc)}"
                )
        subtitle_ms = int((time.monotonic() - subtitle_started) * 1000)

        if subtitle_result["found"]:
            total_ms = int((time.monotonic() - started) * 1000)
            if progress_callback:
                progress_callback("completed", "자막 전사 완료")
            return {
                "transcript": subtitle_result["transcript"],
                "source": "subtitle",
                "subtitle_status": subtitle_result["status"],
                "subtitle_language": subtitle_result.get("language"),
                "subtitle_provider": subtitle_result.get("provider"),
                "subtitle_items": subtitle_result.get("items", []),
                "stage": "completed",
                "timings_ms": {
                    "subtitle_probe_ms": subtitle_ms,
                    "total_ms": total_ms,
                },
                "notice": "유튜브 자막을 사용해 빠르게 전사했습니다.",
            }

        if progress_callback:
            progress_callback("subtitle_unavailable", "자막 미확보 - Whisper 전사 준비")
            progress_callback("fallback_asr", "자막 미확보 - 음성 전사로 전환")

        try:
            asr_result = _transcribe_youtube_via_asr(
                url,
                language_code,
                stt_profile,
                tmp_dir,
                progress_callback=progress_callback,
            )
        except RuntimeError as exc:
            if progress_callback:
                progress_callback("fallback_failed", "음성 전사 폴백 실패")
            raise RuntimeError(
                f"자막 미확보 후 Whisper 폴백을 시도했지만 실패했습니다. {str(exc)}"
            )
        total_ms = int((time.monotonic() - started) * 1000)

        if progress_callback:
            progress_callback("completed", "Whisper 전사 완료")

        return {
            "transcript": asr_result["transcript"],
            "source": "asr_fallback",
            "subtitle_status": subtitle_result["status"],
            "subtitle_language": None,
            "next_action": "fallback_asr",
            "stage": "completed",
            "timings_ms": {
                "subtitle_probe_ms": subtitle_ms,
                "fallback_download_ms": asr_result["download_ms"],
                "fallback_transcribe_ms": asr_result["transcribe_ms"],
                "total_ms": total_ms,
            },
            "notice": "유튜브 자막을 확보하지 못해 Whisper 음성 전사로 처리했습니다.",
        }
    finally:
        import shutil as _shutil

        _shutil.rmtree(tmp_dir, ignore_errors=True)


def transcribe_youtube_url(url: str, language: Optional[str] = None, stt_profile: Optional[str] = None) -> str:
    detailed = transcribe_youtube_url_detailed(url, language, stt_profile)
    return detailed.get("transcript", "")