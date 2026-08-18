"""Polish translations of the interface.

Used by scripts/apply_translations.py to fill in yt_dlp_gui_pl.ts.
"""

# Plural forms (Polish: singular / few / many)
PLURALS = {
    '%n item(s)': ['%n pozycja', '%n pozycje', '%n pozycji'],
    'Attempts: %n': ['Prób: %n', 'Próby: %n', 'Prób: %n'],
    '%n downloaded': ['pobrano %n', 'pobrano %n', 'pobrano %n'],
    '%n failed': ['%n niepowodzenie', '%n niepowodzenia', '%n niepowodzeń'],
}

TRANSLATIONS = {
    # ---- Labels: media kind, quality ----
    'Video': 'Wideo',
    'Audio only': 'Tylko dźwięk',
    'Automatic': 'Automatycznie',
    'Ultra quality': 'Bardzo wysoka jakość',
    'High quality': 'Wysoka jakość',
    'Good quality': 'Dobra jakość',
    'Normal quality': 'Normalna jakość',
    'Low quality': 'Niska jakość',
    'Best': 'Najlepsza',
    'Best available': 'Najlepsza dostępna',
    'Lowest': 'Najniższa',
    'best available video and audio': 'najlepszy dostępny obraz i dźwięk',
    'original audio stream': 'oryginalny strumień dźwięku',
    'Auto': 'Auto',
    'Original': 'Oryginał',

    # ---- Labels: states ----
    'Queued': 'W kolejce',
    'Downloading': 'Pobieranie',
    'Processing': 'Przetwarzanie',
    'Processing…': 'Przetwarzanie…',
    'Connecting…': 'Łączenie…',
    'Done': 'Gotowe',
    'With errors': 'Z błędami',
    'Error': 'Błąd',
    'Cancelled': 'Anulowane',
    'Interrupted': 'Przerwane',
    'Unknown': 'Nieznany',

    # ---- Labels: post-processing stages ----
    'Merging video and audio': 'Scalanie obrazu i dźwięku',
    'Changing container': 'Zmiana kontenera',
    'Converting video': 'Konwersja wideo',
    'Extracting audio': 'Wyodrębnianie dźwięku',
    'Writing metadata': 'Zapisywanie metadanych',
    'Parsing metadata': 'Analiza metadanych',
    'Embedding cover art': 'Osadzanie okładki',
    'Embedding subtitles': 'Osadzanie napisów',
    'Converting subtitles': 'Konwersja napisów',
    'Converting cover art': 'Konwersja okładki',
    'Fetching SponsorBlock data': 'Pobieranie danych SponsorBlock',
    'Removing segments': 'Wycinanie fragmentów',
    'Splitting chapters': 'Dzielenie na rozdziały',
    'Moving file': 'Przenoszenie pliku',
    'Concatenating files': 'Łączenie plików',
    'Fixing file': 'Naprawa pliku',

    # ---- Labels: errors ----
    'This video is private.': 'Materiał jest prywatny.',
    'This video is age-restricted.': 'Materiał ma ograniczenie wiekowe.',
    'This video requires signing in.': 'Materiał wymaga zalogowania.',
    'This video is blocked in your region.': 'Materiał jest zablokowany w Twoim regionie.',
    'This video was removed or is unavailable.': 'Materiał został usunięty lub jest niedostępny.',
    'This address is not supported.': 'Ten adres nie jest obsługiwany.',
    'Invalid address.': 'Nieprawidłowy adres.',
    'The selected format is not available.': 'Wybrany format jest niedostępny.',
    'No downloadable formats were found.': 'Nie znaleziono formatów do pobrania.',
    'FFmpeg was not found.': 'Nie znaleziono FFmpeg.',
    'Network problem.': 'Problem z połączeniem sieciowym.',
    'SSL certificate error.': 'Błąd certyfikatu SSL.',
    'Proxy connection error.': 'Błąd połączenia przez proxy.',
    'No permission to write to the selected folder.': 'Brak uprawnień do zapisu w wybranym katalogu.',
    'No space left on the disk.': 'Brak miejsca na dysku.',
    'Post-processing failed.': 'Błąd przetwarzania po pobraniu.',
    'Could not merge video and audio.': 'Nie udało się scalić obrazu z dźwiękiem.',
    'The live stream has not started yet.': 'Transmisja jeszcze się nie rozpoczęła.',
    'Nothing was found at this address.': 'Nie znaleziono nic pod tym adresem.',
    'The playlist could not be fully retrieved.': 'Nie udało się wczytać całej playlisty.',
    'It needs an account with access — try browser cookies.':
        'Wymaga konta z dostępem — spróbuj ciasteczek z przeglądarki.',
    'Enable browser cookies in Preferences → Network.':
        'Włącz ciasteczka z przeglądarki w Preferencjach → Sieć.',
    'A proxy set in Preferences → Network may help.':
        'Może pomóc proxy ustawione w Preferencjach → Sieć.',
    'yt-dlp has no extractor for this site.': 'yt-dlp nie ma ekstraktora dla tej strony.',
    'Pick another quality or “Best available”.': 'Wybierz inną jakość albo „Najlepsza dostępna”.',
    'The video may be DRM protected.': 'Materiał może być chroniony DRM.',
    'Install FFmpeg or set its folder in Preferences → Network.':
        'Zainstaluj FFmpeg albo wskaż jego katalog w Preferencjach → Sieć.',
    'Check your connection and try again.': 'Sprawdź połączenie i spróbuj ponownie.',
    'Check the proxy address in Preferences → Network.':
        'Sprawdź adres proxy w Preferencjach → Sieć.',
    'Choose a different destination folder.': 'Wskaż inny katalog docelowy.',
    'Check whether FFmpeg is installed.': 'Sprawdź, czy FFmpeg jest zainstalowany.',
    'This usually means FFmpeg is missing or too old.':
        'Zwykle oznacza to brak lub zbyt starą wersję FFmpeg.',

    # ---- Labels: progress and results ----
    'ETA {0}': 'pozostało {0}',
    'fragment {0}/{1}': 'fragment {0}/{1}',
    'Download completed': 'Pobieranie zakończone',
    'Completed with errors': 'Zakończono z błędami',
    'Download failed': 'Pobieranie nieudane',
    'Download cancelled': 'Pobieranie anulowane',
    'The playlist could not be fully retrieved — some items may be missing.':
        'Nie udało się wczytać całej playlisty — część pozycji może brakować.',
    'The playlist could not be retrieved.': 'Nie udało się wczytać playlisty.',
    'Could not download {0} of {1} items.': 'Nie udało się pobrać {0} z {1} pozycji.',
    'at least {0}': 'co najmniej {0}',
    'now: {0}': 'teraz: {0}',
    'the full playlist could not be retrieved': 'nie udało się wczytać całej playlisty',

    # ---- Labels: themes and tabs ----
    'Light': 'Jasny',
    'Dark': 'Ciemny',
    'Steel': 'Stalowy',
    'All': 'Wszystkie',
    'In progress': 'W trakcie',
    'Audio': 'Audio',
    'Playlists': 'Playlisty',
    'Completed': 'Ukończone',

    # ---- DownloadDialog ----
    'Download item': 'Pobierz materiał',
    'Cancel': 'Anuluj',
    'Download': 'Pobierz',
    'unknown': 'nieznany',
    'yt-dlp selector: {0}   ·   estimated size: {1}':
        'Selektor yt-dlp: {0}   ·   szacowany rozmiar: {1}',
    'FFmpeg was not found — merging video with audio, audio conversion and embedding cover art '
    'or subtitles are unavailable.':
        'Nie znaleziono FFmpeg — scalanie obrazu z dźwiękiem, konwersja audio oraz osadzanie '
        'okładek i napisów są niedostępne.',

    # ---- EmptyState ----
    'Copy a link to a video, playlist or channel and click <b>Paste link</b>':
        'Skopiuj link do filmu, playlisty lub kanału i kliknij <b>Wklej link</b>',
    'Every site yt-dlp knows is supported. Save video as MP4, MKV or WebM, audio as MP3, M4A, '
    'Opus or FLAC — together with cover art, tags and subtitles.':
        'Obsługiwane są wszystkie serwisy znane yt-dlp. Wideo zapiszesz jako MP4, MKV lub WebM, '
        'dźwięk jako MP3, M4A, Opus czy FLAC — razem z okładką, tagami i napisami.',

    # ---- FormatWidget ----
    'Format:': 'Format:',
    'Advanced view': 'Widok zaawansowany',
    'Show individual streams: codec, FPS, container':
        'Pokaż pojedyncze strumienie: kodek, FPS, kontener',
    'Extracting audio requires FFmpeg': 'Wyodrębnianie dźwięku wymaga FFmpeg',
    'Changing the container requires FFmpeg': 'Zmiana kontenera wymaga FFmpeg',

    # ---- LogDock ----
    'Log': 'Dziennik',
    'Show diagnostic messages': 'Pokaż komunikaty diagnostyczne',
    'Copy': 'Kopiuj',
    'Clear': 'Wyczyść',

    # ---- MainWindow ----
    'Search…': 'Szukaj…',
    'The clipboard contains no address': 'W schowku nie ma adresu',
    'The full playlist could not be loaded — found {0}, more may exist.':
        'Nie udało się wczytać całej playlisty — znaleziono {0}, mogą być kolejne.',
    'Open file': 'Otwórz plik',
    'Show in folder': 'Pokaż w katalogu',
    'Copy address': 'Kopiuj adres',
    'Download again': 'Pobierz ponownie',
    'Remove from list': 'Usuń z listy',
    'Remove completed': 'Usuń ukończone',
    'Settings saved': 'Ustawienia zapisane',
    'Download folder': 'Katalog pobrań',
    'Analysing {0}…': 'Analizuję {0}…',
    'queued: {0}': 'w kolejce: {0}',
    'errors: {0}': 'błędy: {0}',
    'completed with errors: {0}': 'ukończone z błędami: {0}',
    'paused': 'wstrzymane',
    'All downloads finished': 'Wszystkie pobrania zakończone',
    'Finished with errors — see the log for details':
        'Zakończono z błędami — szczegóły w dzienniku',
    'Ready': 'Gotowy',
    'Close the program?': 'Zamknąć program?',
    'A download is in progress. Closing will interrupt it. Continue?':
        'Trwa pobieranie. Zamknięcie przerwie je. Kontynuować?',

    # ---- MediaInfoWidget ----
    'LIVE': 'NA ŻYWO',

    # ---- OptionsWidget ----
    'Download subtitles': 'Pobierz napisy',
    'Language:': 'Język:',
    'Embed in file': 'Osadź w pliku',
    'Save metadata': 'Zapisz metadane',
    'Embed cover art': 'Osadź okładkę',
    'Save chapters': 'Zapisz rozdziały',
    'Destination folder': 'Katalog docelowy',
    'Choose destination folder': 'Wybierz katalog docelowy',
    'This item offers no subtitles': 'Ten materiał nie udostępnia napisów',
    'Embedding subtitles requires FFmpeg': 'Osadzanie napisów wymaga FFmpeg',
    'Requires FFmpeg': 'Wymaga FFmpeg',
    'Preferred ({0})': 'Preferowane ({0})',
    ' (auto)': ' (auto)',
    'All available': 'Wszystkie dostępne',

    # ---- PlaylistDialog ----
    'Download playlist': 'Pobierz playlistę',
    'The full playlist could not be loaded. Below are the items that could be read; '
    'more may exist.':
        'Nie udało się wczytać całej playlisty. Poniżej są pozycje, które udało się odczytać; '
        'dalsze mogą istnieć.',
    'Select all': 'Zaznacz wszystkie',
    'Deselect all': 'Odznacz wszystkie',
    'Quality:': 'Jakość:',
    'Separate folder': 'Osobny katalog',
    'Number files': 'Numeruj pliki',
    'Add the playlist position before the file name':
        'Dodawaj numer pozycji playlisty przed nazwą pliku',
    'Add to queue': 'Dodaj do kolejki',
    'Selected {0} of {1}': 'Zaznaczono {0} z {1}',

    # ---- SettingsDialog ----
    'Preferences': 'Preferencje',
    'General': 'Ogólne',
    'Files': 'Pliki',
    'Metadata and cover art': 'Metadane i okładki',
    'Subtitles': 'Napisy',
    'Network and FFmpeg': 'Sieć i FFmpeg',
    'Save': 'Zapisz',
    'Appearance': 'Wygląd',
    'Theme:': 'Motyw:',
    'Changes apply immediately. Cancelling restores the previous choice.':
        'Zmiany działają natychmiast. Anulowanie przywraca poprzedni wybór.',
    'Download folder:': 'Katalog pobrań:',
    'Choose…': 'Wybierz…',
    'Choose folder': 'Wybierz katalog',
    'Default mode:': 'Domyślny tryb:',
    'Default quality:': 'Domyślna jakość:',
    'Default video container:': 'Domyślny kontener wideo:',
    'Default audio format:': 'Domyślny format audio:',
    'Automatic mode — download at once, without the format window':
        'Tryb automatyczny — pobieraj od razu, bez okna wyboru formatu',
    'Start downloading as soon as items are queued':
        'Startuj pobieranie zaraz po dodaniu do kolejki',
    'Verbose log (diagnostics)': 'Szczegółowy dziennik (diagnostyka)',
    'Ready-made patterns:': 'Gotowe schematy:',
    'File name:': 'Nazwa pliku:',
    'yt-dlp fields such as %(title)s, %(id)s, %(uploader)s, %(ext)s.':
        'Pola yt-dlp, m.in. %(title)s, %(id)s, %(uploader)s, %(ext)s.',
    'Create a separate folder for playlists': 'Twórz osobny katalog dla playlist',
    'Number playlist files': 'Numeruj pliki playlisty',
    'The playlist name is only used as a folder — never as part of the file name.':
        'Nazwa playlisty służy wyłącznie jako katalog — nigdy jako część nazwy pliku.',
    'Limit file names to ASCII characters': 'Ogranicz nazwy plików do znaków ASCII',
    'Overwrite existing files': 'Nadpisuj istniejące pliki',
    'Save tags (title, author, date, description)':
        'Zapisuj tagi (tytuł, autor, data, opis)',
    'Embed cover art in the file': 'Osadzaj okładkę w pliku',
    'Supported containers: MP3, M4A/MP4, MKV/MKA, OPUS, FLAC.':
        'Obsługiwane kontenery: MP3, M4A/MP4, MKV/MKA, OPUS, FLAC.',
    'Also save cover art as a separate image': 'Zapisuj okładkę także jako osobny obrazek',
    'Split “Artist - Title” into separate tags (audio mode)':
        'Rozbijaj „Artysta - Tytuł” na osobne tagi (tryb audio)',
    'Save full metadata next to the file (.info.json)':
        'Zapisuj pełne metadane obok pliku (.info.json)',
    'Save the description to a .description file': 'Zapisuj opis do pliku .description',
    'SponsorBlock — cut out segments': 'SponsorBlock — wycinanie fragmentów',
    'Sponsors': 'Sponsorzy',
    'Self-promotion': 'Autopromocja',
    'Intro': 'Intro',
    'Outro': 'Outro',
    'Subscription reminders': 'Prośby o subskrypcję',
    'Non-music sections': 'Fragmenty pozamuzyczne',
    'Download subtitles by default': 'Domyślnie pobieraj napisy',
    'Allow automatically generated subtitles': 'Dopuszczaj napisy generowane automatycznie',
    'Embed subtitles in the video file': 'Osadzaj napisy w pliku wideo',
    'Preferred languages:': 'Preferowane języki:',
    'Comma-separated language codes; “all” downloads everything available. The download window '
    'narrows the list to subtitles the item actually has.':
        'Kody języków po przecinku; „all” pobiera wszystkie dostępne. Okno pobierania zawęża '
        'listę do napisów, które materiał faktycznie ma.',
    'Speed limit:': 'Limit prędkości:',
    'no limit, e.g. 2M or 500K': 'bez limitu, np. 2M albo 500K',
    'Parallel fragments:': 'Równoległe fragmenty:',

    'Proxy:': 'Proxy:',
    'e.g. socks5://127.0.0.1:1080': 'np. socks5://127.0.0.1:1080',
    'Cookies from browser:': 'Ciasteczka z przeglądarki:',
    'Cookie file:': 'Plik ciasteczek:',
    'Cookie file': 'Plik ciasteczek',
    'cookies.txt file (optional)': 'plik cookies.txt (opcjonalnie)',
    'Cookies allow downloading private or age-restricted items and items that require signing in.':
        'Ciasteczka pozwalają pobierać materiały prywatne, z ograniczeniem wieku oraz wymagające '
        'zalogowania.',
    'FFmpeg': 'FFmpeg',
    'FFmpeg folder:': 'Katalog FFmpeg:',
    'detect automatically': 'wykryj automatycznie',
    'Status:': 'Stan:',
    '— do not use —': '— nie używaj —',
    '— custom —': '— własny —',
    'Title': 'Tytuł',
    'Title [ID]': 'Tytuł [ID]',
    'Author - Title': 'Autor - Tytuł',
    'Date - Title': 'Data - Tytuł',
    'Text files (*.txt);;All files (*)': 'Pliki tekstowe (*.txt);;Wszystkie pliki (*)',

    # ---- Duplicates and review ----
    'Needs review': 'Do akceptacji',
    'Decision required': 'Wymaga decyzji',
    'Skipped': 'Pominięte',
    'These items need your decision:': 'Te pozycje wymagają Twojej decyzji:',
    'Download all': 'Pobierz wszystkie',
    'Skip': 'Pomiń',
    'Skip all': 'Pomiń wszystkie',
    'More actions': 'Więcej akcji',
    'Download all in current queue': 'Pobierz wszystkie w aktualnej kolejce',
    'Skip all in current queue': 'Pomiń wszystkie w aktualnej kolejce',
    'Duplicate found — “{0}” needs your decision.':
        'Znaleziono duplikat — „{0}” wymaga decyzji.',
    'This item has already been downloaded.': 'Ten materiał został już pobrany.',
    'The same item is already in the queue.': 'Ten materiał jest już w kolejce.',
    'Existing file: {0}': 'Istniejący plik: {0}',
    'New destination: {0}': 'Nowy katalog: {0}',
    'Skipped — the file already exists in the destination folder.':
        'Pominięto — plik już istnieje w katalogu docelowym.',
    'Skipped by you.': 'Pominięte przez Ciebie.',
    'awaiting decision: {0}': 'do akceptacji: {0}',

    # ---- Failures and retries ----
    'yt-dlp retries:': 'Ponowienia yt-dlp:',
    'Job retries:': 'Ponowienia zadania:',
    'Delay between job retries (s):': 'Odstęp między ponowieniami (s):',
    'The first value applies inside a single yt-dlp attempt (HTTP, fragments). '
    'The second repeats the whole job; only after using it up does an item '
    'move to the Failed tab.':
        'Pierwsza wartość działa wewnątrz jednej próby yt-dlp (HTTP, fragmenty). '
        'Druga powtarza całe zadanie; dopiero jej wyczerpanie przenosi pozycję '
        'do zakładki Błędy.',
    'Failed': 'Błędy',
    'Retrying': 'Ponawianie',
    'Retrying…': 'Ponawianie…',
    'Retry': 'Ponów',
    'Retry all': 'Ponów wszystkie',
    'Remove': 'Usuń',
    'Remove all': 'Usuń wszystkie',
    'Show details': 'Pokaż szczegóły',
    'These downloads did not succeed:': 'Tych pozycji nie udało się pobrać:',
    'Last attempt: {0}': 'Ostatnia próba: {0}',
    'manual': 'ręczna',
    'automatic': 'automatyczna',
    'succeeded': 'powodzenie',
    'Error details': 'Szczegóły błędu',
    'Close': 'Zamknij',
    'Attempt history': 'Historia prób',
    'Full message from yt-dlp': 'Pełny komunikat yt-dlp',
    'Category: {0}': 'Kategoria: {0}',
    'Address: {0}': 'Adres: {0}',
    'Playlist: {0}': 'Playlista: {0}',
    'No recorded attempts': 'Brak zapisanych prób',
    'Could not download “{0}”. See the Failed tab.':
        'Nie udało się pobrać „{0}”. Zajrzyj do zakładki Błędy.',
    'Remove entries?': 'Usunąć wpisy?',
    'Remove all failed entries from history?\n\nDownloaded files will not be deleted.':
        'Usunąć z historii wszystkie nieudane wpisy?\n\nPobrane pliki nie zostaną usunięte.',

    'Could not save download history. The download itself is unaffected.':
        'Nie udało się zapisać historii pobierania. Samo pobieranie działa normalnie.',

    # ---- Accessible names ----
    'What to download': 'Co pobrać',
    'Default quality': 'Domyślna jakość',
    'Default format': 'Domyślny format',
    'Quality': 'Jakość',
    'Format': 'Format',
    'Subtitle language': 'Język napisów',
    'Playlist items': 'Pozycje playlisty',
    'Original message from yt-dlp': 'Oryginalny komunikat z yt-dlp',
    'Search downloads': 'Szukaj w pobraniach',
    'Download queue': 'Kolejka pobrań',
    'Settings sections': 'Sekcje ustawień',
    'Choose cookies file': 'Wybierz plik ciasteczek',
    'Choose FFmpeg location': 'Wskaż lokalizację FFmpeg',

    # ---- Dependency warnings ----
    'FFmpeg was not found. Merging, conversion and audio extraction will not work.':
        'Nie znaleziono FFmpeg. Scalanie, konwersja i wyodrębnianie dźwięku nie zadziałają.',
    'No supported JavaScript runtime was found. Some YouTube formats may be unavailable.':
        'Nie znaleziono obsługiwanego środowiska JavaScript. '
        'Część formatów YouTube może być niedostępna.',

    # ---- About and diagnostics ----
    'About {0}': 'O programie {0}',
    'Version {0}': 'Wersja {0}',
    'A desktop graphical interface for yt-dlp.':
        'Graficzny interfejs desktopowy dla yt-dlp.',
    'Built with': 'Zbudowano z',
    'Project': 'Projekt',
    'Licence text': 'Tekst licencji',
    'Project repository': 'Repozytorium projektu',
    'Released under {0}.': 'Udostępniony na licencji {0}.',
    'View licence': 'Pokaż licencję',
    'Hide licence': 'Ukryj licencję',
    'not found': 'nie znaleziono',
    'Diagnostics': 'Diagnostyka',
    'Version and dependencies': 'Wersja i zależności',
    'Copy system information': 'Kopiuj informacje o systemie',
    'Copied': 'Skopiowano',
    'Attach this to a bug report. Paths and versions only; nothing personal.':
        'Dołącz to do zgłoszenia błędu. Tylko ścieżki i wersje, nic osobistego.',

    # ---- History ----
    'Download history': 'Historia pobrań',
    'Stored records:': 'Zapisane wpisy:',
    'Clear history': 'Wyczyść historię',
    'Downloaded files will not be deleted.': 'Pobrane pliki nie zostaną usunięte.',
    'Are you sure you want to clear download history?\n\nThis removes download records, '
    'but does not delete downloaded files from the disk.':
        'Czy na pewno chcesz wyczyścić historię pobrań?\n\nTa operacja usunie informacje '
        'o wcześniejszych pobraniach, ale nie usunie pobranych plików z dysku.',
    'History cleared': 'Historia została wyczyszczona',
    'Remove from history': 'Usuń z historii',

    # ---- TopBar ----
    'Paste link': 'Wklej link',
    'Add addresses from the clipboard (Ctrl+V)': 'Dodaj adresy ze schowka (Ctrl+V)',
    'Download:': 'Pobierz:',
    'Save to:': 'Zapisz do:',
    'Resume the queue': 'Wznów kolejkę',
    'Pause after the current download': 'Wstrzymaj po bieżącym pobraniu',
    'Cancel selected': 'Anuluj zaznaczone',
    'Show or hide the log': 'Pokaż lub ukryj dziennik',
}
