"""Format discovery and construction of yt-dlp `-f` selectors.

The selectors follow the syntax documented in the README of the local yt-dlp
repository (the "FORMAT SELECTION" section), among others the patterns:

    bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4] / bv*+ba/b
    bv*[height<=480]+ba/b[height<=480] / wv*+ba/w

No `format_id` is hard-coded; everything is derived from `info_dict`.
"""

from __future__ import annotations

from ..utils import formatting as fmt
from .models import (
    QUALITY_BEST,
    QUALITY_WORST,
    DownloadRequest,
    FormatInfo,
    FormatVariant,
    MediaKind,
    QualityGrade,
    QualityOption,
)

#: Video containers offered in the GUI ('' = keep the source one).
#: `app/gui/labels.py` builds the user-facing labels; core knows no language.
VIDEO_CONTAINERS: tuple[str, ...] = ('', 'mp4', 'mkv', 'webm')

#: Audio codecs supported by FFmpegExtractAudioPP ('' = no conversion)
AUDIO_FORMATS: tuple[str, ...] = ('mp3', 'm4a', 'aac', 'opus', 'flac', 'wav', '')

#: Generic quality ladder, used before the media formats are known (top bar,
#: playlists, preferences). For a concrete media item the list comes from
#: `quality_options()` based on `info_dict`.
QUALITY_LADDER: tuple[int, ...] = (0, 2160, 1440, 1080, 720, 480, 360)

#: Audio quality steps (kbps), used when the media exposes none of its own
AUDIO_QUALITY_STEPS: tuple[int, ...] = (320, 256, 192, 160, 128, 96)

#: Colloquial resolution names; technical shorthands, identical in every language
HEIGHT_ALIASES = {4320: '8K', 2160: '4K', 1440: '2K', 1080: 'Full HD', 720: 'HD'}

_VCODEC_NAMES = (
    ('avc1', 'H.264'), ('h264', 'H.264'), ('hev1', 'H.265'), ('hvc1', 'H.265'), ('h265', 'H.265'),
    ('av01', 'AV1'), ('vp09', 'VP9'), ('vp9', 'VP9'), ('vp8', 'VP8'), ('theora', 'Theora'),
)
_ACODEC_NAMES = (
    ('mp4a', 'AAC'), ('aac', 'AAC'), ('opus', 'Opus'), ('vorbis', 'Vorbis'), ('mp3', 'MP3'),
    ('ec-3', 'E-AC3'), ('ac-3', 'AC3'), ('flac', 'FLAC'), ('alac', 'ALAC'), ('dts', 'DTS'),
)

# Containers worth narrowing the selector to compatible streams for, so that
# merging does not require transcoding.
_EXT_PREFERENCE = {
    'mp4': ('mp4', 'm4a'),
    'webm': ('webm', 'webm'),
}


# ------------------------------------------------------------------------- parsing


def _codec_name(codec: str | None, table) -> str:
    if not codec or codec == 'none':
        return ''
    low = codec.lower()
    for prefix, name in table:
        if low.startswith(prefix):
            return name
    return codec.split('.')[0].upper()


def video_codec_name(codec: str | None) -> str:
    return _codec_name(codec, _VCODEC_NAMES)


def audio_codec_name(codec: str | None) -> str:
    return _codec_name(codec, _ACODEC_NAMES)


def parse_formats(raw_formats) -> tuple[FormatInfo, ...]:
    """`info_dict['formats']` -> a tuple of `FormatInfo` (storyboards excluded)."""
    parsed = []
    for raw in raw_formats or []:
        if not isinstance(raw, dict) or not raw.get('format_id'):
            continue
        info = FormatInfo(
            format_id=str(raw['format_id']),
            ext=raw.get('ext'),
            width=raw.get('width'),
            height=raw.get('height'),
            resolution=raw.get('resolution'),
            fps=raw.get('fps'),
            vcodec=raw.get('vcodec'),
            acodec=raw.get('acodec'),
            tbr=raw.get('tbr'),
            vbr=raw.get('vbr'),
            abr=raw.get('abr'),
            filesize=raw.get('filesize'),
            filesize_approx=raw.get('filesize_approx'),
            protocol=raw.get('protocol'),
            format_note=raw.get('format_note'),
            language=raw.get('language'),
            dynamic_range=raw.get('dynamic_range'),
        )
        if info.is_storyboard or not (info.has_video or info.has_audio):
            continue
        parsed.append(info)
    return tuple(parsed)


def best_audio(formats) -> FormatInfo | None:
    """Best audio-only stream, used for size estimates and v+a pairs."""
    audio = [f for f in formats if f.is_audio_only]
    if not audio:
        return None
    return max(audio, key=lambda f: (f.bitrate or 0, f.size or 0))


def available_heights(formats) -> list[int]:
    """Resolutions actually available for the media, in descending order."""
    return sorted({f.height for f in formats if f.has_video and f.height}, reverse=True)


def height_label(height: int) -> str:
    """`1080` -> `1080p (Full HD)`; a technical shorthand, same in every language."""
    alias = HEIGHT_ALIASES.get(height)
    return f'{height}p ({alias})' if alias else f'{height}p'


def _grade_for_height(height: int) -> QualityGrade:
    if height >= 2160:
        return QualityGrade.ULTRA
    if height >= 1080:
        return QualityGrade.HIGH
    if height >= 720:
        return QualityGrade.GOOD
    if height >= 360:
        return QualityGrade.NORMAL
    return QualityGrade.LOW


def _grade_for_bitrate(abr: float) -> QualityGrade:
    if abr >= 256:
        return QualityGrade.ULTRA
    if abr >= 160:
        return QualityGrade.HIGH
    if abr >= 112:
        return QualityGrade.NORMAL
    return QualityGrade.LOW


def _best_video_at(formats, height: int, prefer_ext: str = '') -> FormatInfo | None:
    """Best video stream at the given height.

    `prefer_ext` reflects the container chosen in the GUI, so the description
    in the quality list matches what will actually be downloaded.
    """
    candidates = [f for f in formats if f.has_video and f.height == height]
    if not candidates:
        return None
    return max(candidates, key=lambda f: (
        f.ext == prefer_ext if prefer_ext else False,
        f.tbr or f.vbr or 0,
        f.ext == 'mp4',
    ))


def _combined_size(video: FormatInfo, audio: FormatInfo | None) -> int | None:
    if video.is_muxed or audio is None:
        return video.size
    if video.size and audio.size:
        return video.size + audio.size
    return video.size


# ------------------------------------------------------ simple quality selector


def quality_options(formats, prefer_ext: str = '') -> list[QualityOption]:
    """Quality list for the simple selector, restricted to what really exists.

    It always starts with "Best available"; 4K never appears when the media
    tops out at 1080p.
    """
    options = [QualityOption(value=QUALITY_BEST, label='', grade=QualityGrade.AUTOMATIC)]

    audio = best_audio(formats)
    for height in available_heights(formats):
        video = _best_video_at(formats, height, prefer_ext)
        if video is None:
            continue
        acodec = audio_codec_name(video.acodec if video.is_muxed else (audio.acodec if audio else None))
        options.append(QualityOption(
            value=height,
            label=height_label(height),
            grade=_grade_for_height(height),
            details=fmt.dot_join(
                (video.ext or '').upper(),
                video_codec_name(video.vcodec),
                acodec,
                fmt.fps(video.fps) if video.fps and video.fps >= 50 else '',
            ),
            filesize=_combined_size(video, audio),
        ))
    return options


def audio_quality_options(formats) -> list[QualityOption]:
    """Qualities for audio-only mode, derived from the available streams."""
    options = [QualityOption(value=QUALITY_BEST, label='', grade=QualityGrade.AUTOMATIC)]

    seen: set[int] = set()
    for track in sorted((f for f in formats if f.is_audio_only),
                        key=lambda f: f.bitrate or 0, reverse=True):
        rate = round(track.bitrate or 0)
        if not rate or rate in seen:
            continue
        seen.add(rate)
        options.append(QualityOption(
            value=rate,
            label=fmt.bitrate(rate),
            grade=_grade_for_bitrate(rate),
            details=fmt.dot_join((track.ext or '').upper(), audio_codec_name(track.acodec)),
            filesize=track.size,
        ))
    if len(options) == 1:
        # The media exposes no separate audio tracks; show the usual steps
        options.extend(QualityOption(
            value=rate, label=fmt.bitrate(rate), grade=_grade_for_bitrate(rate),
        ) for rate in AUDIO_QUALITY_STEPS)
    return options


# ---------------------------------------------------- advanced format selection


def video_variants(formats) -> list[FormatVariant]:
    """Konkretne warianty wideo: '1080p • 60 FPS • H.264 • MP4'.

    Video-only streams are combined with the best audio (`id+id`); muxed ones
    are left as they are.
    """
    audio = best_audio(formats)
    variants: list[FormatVariant] = []
    seen: set[tuple] = set()

    for video in sorted((f for f in formats if f.has_video),
                        key=lambda f: (f.height or 0, f.fps or 0, f.tbr or 0), reverse=True):
        # Key on the normalised codec name; otherwise 'avc1.4d401e' and
        # 'avc1.42001E' masquerade as two variants of the same H.264
        key = (video.height, round(video.fps or 0), video_codec_name(video.vcodec), video.ext)
        if key in seen:
            continue
        seen.add(key)

        if video.is_muxed or audio is None:
            selector = video.format_id
        else:
            selector = f'{video.format_id}+{audio.format_id}'

        variants.append(FormatVariant(
            selector=selector,
            label=fmt.dot_join(
                video.height_label,
                fmt.fps(video.fps),
                video_codec_name(video.vcodec),
                (video.ext or '').upper(),
                video.dynamic_range if video.dynamic_range not in (None, 'SDR') else '',
            ),
            grade=_grade_for_height(video.height or 0),
            filesize=_combined_size(video, audio),
            height=video.height,
        ))
    return variants


def audio_variants(formats) -> list[FormatVariant]:
    """Konkretne warianty audio: '160 kbps • Opus • WEBM'."""
    variants: list[FormatVariant] = []
    seen: set[tuple] = set()

    for track in sorted((f for f in formats if f.is_audio_only),
                        key=lambda f: f.bitrate or 0, reverse=True):
        key = (round(track.bitrate or 0), audio_codec_name(track.acodec), track.ext)
        if key in seen:
            continue
        seen.add(key)
        variants.append(FormatVariant(
            selector=track.format_id,
            label=fmt.dot_join(
                fmt.bitrate(track.bitrate),
                audio_codec_name(track.acodec),
                (track.ext or '').upper(),
                track.language or '',
            ),
            grade=_grade_for_bitrate(track.bitrate or 0),
            filesize=track.size,
            height=None,
            abr=track.bitrate,
        ))
    return variants


# --------------------------------------------------------- building the selector


def build_selector(request: DownloadRequest) -> str:
    """The `-f` selector for a request.

    A manual pick from the advanced view takes precedence over the quality.
    """
    if request.format_selector:
        return request.format_selector
    if request.kind is MediaKind.AUDIO:
        return _audio_selector(request)
    return _video_selector(request)


def _audio_selector(request: DownloadRequest) -> str:
    """Audio only; FFmpegExtractAudioPP handles the container conversion."""
    preferred = ''
    if request.audio_format in ('m4a', 'aac'):
        preferred = 'ba[ext=m4a]/'
    elif request.audio_format == 'opus':
        preferred = 'ba[acodec=opus]/'

    if request.quality > 0:
        # Do not go lower than needed, nor pay for a stream better than the target
        return f'{preferred}ba[abr<={request.quality}]/ba/b'
    if request.quality == QUALITY_WORST:
        return 'wa/w'
    return f'{preferred}ba/b'


def _video_selector(request: DownloadRequest) -> str:
    if request.quality == QUALITY_WORST:
        return 'wv*+wa/w'

    limit = f'[height<={request.quality}]' if request.quality > QUALITY_BEST else ''
    generic = f'bv*{limit}+ba/b{limit}'
    fallback = 'bv*+ba/b'

    exts = _EXT_PREFERENCE.get(request.container)
    if not exts:
        # MKV and auto mode: any streams, merging takes care of the rest
        return f'{generic}/{fallback}' if limit else fallback

    video_ext, audio_ext = exts
    preferred = f'bv*{limit}[ext={video_ext}]+ba[ext={audio_ext}]/b{limit}[ext={video_ext}]'
    return f'{preferred}/{generic}/{fallback}'
