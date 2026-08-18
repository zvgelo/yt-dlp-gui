"""Domain layer: models, yt-dlp service, format selection, queue controller.

Modules here stay free of PySide6 except `download_controller`, which is a
QObject by design: it is the seam between the domain and the GUI.
"""
