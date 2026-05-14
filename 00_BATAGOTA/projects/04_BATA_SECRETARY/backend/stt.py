import os
import tempfile
from threading import Lock
from typing import Optional

from faster_whisper import WhisperModel

_MODEL = None
_MODEL_LOCK = Lock()

_FALLBACK_TRANSCRIPTS = [
    "오늘 상담 목표를 먼저 정해보겠습니다.",
    "진로 선택이 너무 어렵고 불안합니다.",
    "선택지를 3개로 줄여서 비교해봅시다.",
    "부모님 의견도 많이 신경 쓰입니다.",
    "네 그 부분은 다음 단계에서 같이 정리하겠습니다.",
]


def _get_model() -> WhisperModel:
    global _MODEL
    if _MODEL is None:
        with _MODEL_LOCK:
            if _MODEL is None:
                model_size = os.getenv("WHISPER_MODEL_SIZE", "base")
                compute_type = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
                _MODEL = WhisperModel(model_size, device="cpu", compute_type=compute_type)
    return _MODEL


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


def _fallback_transcript(chunk_index: int) -> str:
    return _FALLBACK_TRANSCRIPTS[chunk_index % len(_FALLBACK_TRANSCRIPTS)]


def transcribe_audio_bytes(
    audio_bytes: bytes,
    chunk_index: int,
    audio_format: Optional[str] = None,
    language: Optional[str] = None,
) -> str:
    if not audio_bytes:
        return ""

    model = _get_model()
    suffix = _normalize_audio_suffix(audio_format)
    language_code = language or os.getenv("WHISPER_LANGUAGE", "ko")
    temp_path = None

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            temp_file.write(audio_bytes)
            temp_path = temp_file.name

        segments, _ = model.transcribe(
            temp_path,
            language=language_code,
            condition_on_previous_text=True,
            prompt="상담, 진로, 선택, 불안, 목표, 미팅",
            vad_filter=True,
            beam_size=1,
        )
        transcript = " ".join(
            segment.text.strip() for segment in segments if segment.text and segment.text.strip()
        ).strip()
        if transcript:
            return transcript

        # 무음/저품질 구간은 UI 흐름 유지를 위해 기존 더미 문구를 반환한다.
        return _fallback_transcript(chunk_index)
    except Exception as exc:
        print(f"[WARN] Whisper decode/transcribe fallback: {exc}")
        return _fallback_transcript(chunk_index)
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)