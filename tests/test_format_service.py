"""Tests for format selection: logic independent of the GUI."""

from __future__ import annotations

import pytest

from app.core import format_service as fs
from app.core.models import QUALITY_BEST, QUALITY_WORST, DownloadRequest, MediaKind

RAW_FORMATS = [
    {'format_id': '140', 'ext': 'm4a', 'acodec': 'mp4a.40.2', 'vcodec': 'none',
     'abr': 128, 'filesize': 4_600_000},
    {'format_id': '251', 'ext': 'webm', 'acodec': 'opus', 'vcodec': 'none',
     'abr': 160, 'filesize': 5_200_000},
    {'format_id': '137', 'ext': 'mp4', 'vcodec': 'avc1.640028', 'acodec': 'none',
     'height': 1080, 'width': 1920, 'fps': 30, 'tbr': 4000, 'filesize': 60_100_000},
    {'format_id': '303', 'ext': 'webm', 'vcodec': 'vp09.00.40.08', 'acodec': 'none',
     'height': 1080, 'width': 1920, 'fps': 60, 'tbr': 4500, 'filesize': 64_700_000},
    {'format_id': '136', 'ext': 'mp4', 'vcodec': 'avc1.4d401f', 'acodec': 'none',
     'height': 720, 'width': 1280, 'fps': 30, 'tbr': 2400, 'filesize': 33_500_000},
    {'format_id': '18', 'ext': 'mp4', 'vcodec': 'avc1.42001E', 'acodec': 'mp4a.40.2',
     'height': 360, 'width': 640, 'fps': 30, 'tbr': 700, 'filesize': 13_300_000},
    {'format_id': 'sb0', 'ext': 'mhtml', 'vcodec': 'none', 'acodec': 'none',
     'format_note': 'storyboard'},
]


@pytest.fixture
def formats():
    return fs.parse_formats(RAW_FORMATS)


def test_parsing_skips_storyboards(formats):
    assert 'sb0' not in {f.format_id for f in formats}
    assert len(formats) == 6


def test_stream_type_is_recognised(formats):
    by_id = {f.format_id: f for f in formats}
    assert by_id['140'].is_audio_only
    assert by_id['137'].is_video_only
    assert by_id['18'].is_muxed


def test_available_heights_are_never_invented(formats):
    # The media tops out at 1080p, so 4K must not appear
    assert fs.available_heights(formats) == [1080, 720, 360]
    values = [option.value for option in fs.quality_options(formats)]
    assert values == [QUALITY_BEST, 1080, 720, 360]
    assert 2160 not in values


def test_quality_respects_the_chosen_container(formats):
    mp4 = {o.value: o for o in fs.quality_options(formats, 'mp4')}
    webm = {o.value: o for o in fs.quality_options(formats, 'webm')}
    assert 'MP4' in mp4[1080].details
    assert 'WEBM' in webm[1080].details


def test_size_combines_video_and_audio(formats):
    option = next(o for o in fs.quality_options(formats, 'mp4') if o.value == 1080)
    # 137 (60.1 MB) + najlepsze audio 251 (5.2 MB)
    assert option.filesize == 60_100_000 + 5_200_000


def test_advanced_variants_combine_streams(formats):
    variants = fs.video_variants(formats)
    selectors = {v.selector for v in variants}
    assert '303+251' in selectors  # video-only + najlepsze audio
    assert '18' in selectors  # muxed zostaje samo
    assert any('60 FPS' in v.label and 'VP9' in v.label for v in variants)


def test_variants_do_not_duplicate_the_same_codec():
    # 'avc1.4d401e' and 'avc1.42001E' are the same H.264: one row, not two
    raw = [
        {'format_id': 'a', 'ext': 'mp4', 'vcodec': 'avc1.4d401e', 'acodec': 'none',
         'height': 360, 'fps': 30, 'tbr': 600},
        {'format_id': 'b', 'ext': 'mp4', 'vcodec': 'avc1.42001E', 'acodec': 'mp4a.40.2',
         'height': 360, 'fps': 30, 'tbr': 700},
    ]
    assert len(fs.video_variants(fs.parse_formats(raw))) == 1


def test_audio_qualities_come_from_real_streams(formats):
    values = [o.value for o in fs.audio_quality_options(formats)]
    assert values == [QUALITY_BEST, 160, 128]


def test_audio_qualities_fall_back_when_no_tracks_exist():
    raw = [{'format_id': '18', 'ext': 'mp4', 'vcodec': 'avc1', 'acodec': 'mp4a.40.2',
            'height': 360}]
    values = [o.value for o in fs.audio_quality_options(fs.parse_formats(raw))]
    assert values[0] == QUALITY_BEST
    assert 320 in values


@pytest.mark.parametrize(('quality', 'container', 'expected_parts'), [
    (QUALITY_BEST, '', ['bv*+ba/b']),
    (QUALITY_BEST, 'mkv', ['bv*+ba/b']),
    (QUALITY_BEST, 'mp4', ['bv*[ext=mp4]+ba[ext=m4a]', 'bv*+ba/b']),
    (1080, '', ['bv*[height<=1080]+ba/b[height<=1080]']),
    (1080, 'mp4', ['bv*[height<=1080][ext=mp4]+ba[ext=m4a]', 'b[height<=1080][ext=mp4]']),
    (720, 'webm', ['bv*[height<=720][ext=webm]+ba[ext=webm]']),
    (QUALITY_WORST, 'mp4', ['wv*+wa/w']),
])
def test_video_selector(quality, container, expected_parts):
    request = DownloadRequest(url='u', output_dir='/tmp', quality=quality, container=container)
    selector = fs.build_selector(request)
    for part in expected_parts:
        assert part in selector


@pytest.mark.parametrize(('quality', 'audio_format', 'expected'), [
    (QUALITY_BEST, 'mp3', 'ba/b'),
    (QUALITY_BEST, 'm4a', 'ba[ext=m4a]/ba/b'),
    (QUALITY_BEST, 'opus', 'ba[acodec=opus]/ba/b'),
    (192, 'mp3', 'ba[abr<=192]/ba/b'),
    (QUALITY_WORST, 'mp3', 'wa/w'),
])
def test_audio_selector(quality, audio_format, expected):
    request = DownloadRequest(url='u', output_dir='/tmp', kind=MediaKind.AUDIO,
                              quality=quality, audio_format=audio_format)
    assert fs.build_selector(request) == expected


def test_manual_choice_takes_precedence():
    request = DownloadRequest(url='u', output_dir='/tmp', quality=1080, container='mp4',
                              format_selector='303+251')
    assert fs.build_selector(request) == '303+251'


def test_every_selector_is_understood_by_yt_dlp():
    """The key test: yt-dlp must accept every selector we generate."""
    from yt_dlp import YoutubeDL

    ydl = YoutubeDL({'quiet': True, 'no_warnings': True})
    requests = [
        DownloadRequest(url='u', output_dir='/tmp', quality=q, container=c)
        for q in (QUALITY_BEST, 2160, 1080, 480, QUALITY_WORST)
        for c in ('', 'mp4', 'mkv', 'webm')
    ] + [
        DownloadRequest(url='u', output_dir='/tmp', kind=MediaKind.AUDIO, quality=q, audio_format=a)
        for q in (QUALITY_BEST, 320, 128, QUALITY_WORST)
        for a in ('mp3', 'm4a', 'aac', 'opus', 'flac', 'wav', '')
    ]
    for request in requests:
        ydl.build_format_selector(fs.build_selector(request))


def test_codec_names():
    assert fs.video_codec_name('avc1.640028') == 'H.264'
    assert fs.video_codec_name('vp09.00.40.08') == 'VP9'
    assert fs.video_codec_name('av01.0.05M.08') == 'AV1'
    assert fs.audio_codec_name('mp4a.40.2') == 'AAC'
    assert fs.audio_codec_name('none') == ''
