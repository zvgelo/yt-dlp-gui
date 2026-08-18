"""Testy budowania opcji `YoutubeDL` i konwersji info_dict → modele."""

from __future__ import annotations

import pytest

from app.core.models import DownloadRequest, MediaKind
from app.core.ytdlp_service import YtDlpService, build_media_info, final_filepath
from app.settings import AppSettings


@pytest.fixture
def service():
    return YtDlpService(AppSettings(output_dir='/tmp/pobrane'))


def _keys(options):
    return [pp['key'] for pp in options.get('postprocessors', [])]


def test_probe_does_not_download_and_flattens_the_playlist(service):
    options = service.probe_options()
    assert options['skip_download'] is True
    assert options['noplaylist'] is False
    assert options['extract_flat'] == 'in_playlist'


def test_video_mp4_options(service):
    request = DownloadRequest(url='u', output_dir='/tmp/x', quality=1080, container='mp4')
    options = service.download_options(request)

    assert options['merge_output_format'] == 'mp4'
    assert options['final_ext'] == 'mp4'
    assert options['paths'] == {'home': '/tmp/x'}
    assert options['outtmpl']['default'] == '%(title)s.%(ext)s'
    assert 'bv*[height<=1080][ext=mp4]' in options['format']


def test_audio_options_trigger_extraction(service):
    request = DownloadRequest(url='u', output_dir='/tmp/x', kind=MediaKind.AUDIO,
                              audio_format='mp3', quality=192)
    options = service.download_options(request)

    extract = next(pp for pp in options['postprocessors'] if pp['key'] == 'FFmpegExtractAudio')
    assert extract['preferredcodec'] == 'mp3'
    assert extract['preferredquality'] == '192'
    # For audio we set neither a video container nor a remux
    assert 'merge_output_format' not in options
    assert 'FFmpegVideoRemuxer' not in _keys(options)


def test_postprocessor_order_matches_yt_dlp(service):
    """ModifyChapters before FFmpegMetadata, EmbedThumbnail last."""
    service.update_settings(service.settings.replace(sponsorblock_remove='sponsor,intro'))
    request = DownloadRequest(url='u', output_dir='/tmp/x', kind=MediaKind.AUDIO,
                              audio_format='mp3', embed_thumbnail=True, embed_metadata=True)
    keys = _keys(service.download_options(request))

    assert keys.index('SponsorBlock') < keys.index('FFmpegExtractAudio')
    assert keys.index('ModifyChapters') < keys.index('FFmpegMetadata')
    assert keys.index('FFmpegExtractAudio') < keys.index('FFmpegMetadata')
    assert keys[-1] == 'EmbedThumbnail'


def test_cover_art_without_writing_to_disk(service):
    request = DownloadRequest(url='u', output_dir='/tmp/x', embed_thumbnail=True,
                              write_thumbnail=False)
    options = service.download_options(request)

    assert options['writethumbnail'] is True
    assert options['outtmpl']['pl_thumbnail'] == ''
    embed = next(pp for pp in options['postprocessors'] if pp['key'] == 'EmbedThumbnail')
    assert embed['already_have_thumbnail'] is False


def test_subtitles_only_for_video(service):
    video = service.download_options(DownloadRequest(
        url='u', output_dir='/tmp/x', write_subtitles=True, subtitle_languages=('pl', 'en')))
    assert video['writesubtitles'] is True
    assert video['subtitleslangs'] == ['pl', 'en']
    assert 'FFmpegEmbedSubtitle' in _keys(video)

    audio = service.download_options(DownloadRequest(
        url='u', output_dir='/tmp/x', kind=MediaKind.AUDIO, write_subtitles=True))
    assert 'writesubtitles' not in audio
    assert 'FFmpegEmbedSubtitle' not in _keys(audio)


def test_playlist_template(service):
    request = DownloadRequest(url='u', output_dir='/tmp/x', playlist_title='Moja lista',
                              playlist_index=3)
    template = service.download_options(request)['outtmpl']['default']
    assert template == '%(playlist_title)s/%(playlist_index)03d - %(title)s.%(ext)s'


def test_single_media_without_the_playlist_part(service):
    request = DownloadRequest(url='u', output_dir='/tmp/x')
    assert service.download_options(request)['outtmpl']['default'] == '%(title)s.%(ext)s'


def test_rate_limit_and_cookies(service):
    service.update_settings(service.settings.replace(
        rate_limit='2M', cookies_from_browser='firefox', proxy='socks5://127.0.0.1:1080'))
    options = service.download_options(DownloadRequest(url='u', output_dir='/tmp/x'))

    assert options['ratelimit'] == 2 * 1024 * 1024
    assert options['cookiesfrombrowser'] == ('firefox',)
    assert options['proxy'] == 'socks5://127.0.0.1:1080'


def test_an_invalid_rate_limit_does_not_crash(service):
    service.update_settings(service.settings.replace(rate_limit='bardzo szybko'))
    assert 'ratelimit' not in service.download_options(DownloadRequest(url='u', output_dir='/tmp/x'))


def test_the_options_are_accepted_by_youtubedl(service):
    """The built options must be accepted by a real `YoutubeDL`."""
    from yt_dlp import YoutubeDL

    service.update_settings(service.settings.replace(sponsorblock_remove='sponsor'))
    for request in (
        DownloadRequest(url='u', output_dir='/tmp/x', quality=1080, container='mp4'),
        DownloadRequest(url='u', output_dir='/tmp/x', kind=MediaKind.AUDIO, audio_format='flac'),
        DownloadRequest(url='u', output_dir='/tmp/x', write_subtitles=True, container='mkv'),
    ):
        options = service.download_options(request)
        options['quiet'] = True
        with YoutubeDL(options) as ydl:
            assert ydl.params['format'] == options['format']


# --------------------------------------------------------------- info_dict


def test_single_media():
    raw = {
        '_type': 'video',
        'title': 'Title',
        'webpage_url': 'https://example.com/v',
        'uploader': 'Autor',
        'duration': 125,
        'extractor_key': 'Youtube',
        'thumbnails': [{'url': 'https://example.com/a.jpg'}, {'url': 'https://example.com/b.jpg'}],
        'subtitles': {'pl': [{'name': 'polski'}], 'live_chat': [{}]},
        'automatic_captions': {'en': [{'name': 'English'}], 'en-pl': [{}]},
        'formats': [{'format_id': '18', 'ext': 'mp4', 'vcodec': 'avc1', 'acodec': 'mp4a',
                     'height': 360}],
    }
    info = build_media_info('https://example.com/v', raw)

    assert info.is_playlist is False
    assert info.title == 'Title'
    assert info.author == 'Autor'
    assert len(info.formats) == 1
    languages = {track.language for track in info.subtitles}
    assert languages == {'pl', 'en'}  # no live_chat and no 'en-pl' translations
    assert next(t for t in info.subtitles if t.language == 'en').automatic is True


def test_a_playlist_yields_entries():
    raw = {
        '_type': 'playlist',
        'title': 'Lista',
        'entries': [
            {'_type': 'url', 'url': 'https://example.com/1', 'title': 'Jeden', 'duration': 60},
            {'_type': 'url', 'url': 'https://example.com/2', 'title': 'Dwa'},
        ],
    }
    info = build_media_info('https://example.com/list', raw)

    assert info.is_playlist is True
    assert info.entry_count == 2
    assert info.entries[0].index == 1
    assert info.entries[1].title == 'Dwa'


def test_a_nested_playlist_is_flattened():
    raw = {
        '_type': 'playlist', 'title': 'Channel',
        'entries': [{
            '_type': 'playlist', 'title': 'Tab',
            'entries': [{'_type': 'url', 'url': 'https://example.com/1', 'title': 'Jeden'}],
        }],
    }
    info = build_media_info('https://example.com/c', raw)
    assert info.entry_count == 1


def test_file_path_after_postprocessing():
    assert final_filepath({'requested_downloads': [{'filepath': '/tmp/a.mp3'}]}) == '/tmp/a.mp3'
    assert final_filepath({'_filename': '/tmp/b.mp4'}) == '/tmp/b.mp4'
    assert final_filepath(None) == ''
