"""English catalogue.

The source strings in the code are already English, so only the plural forms
need translating; without them Qt would show a literal "%n item(s)".
"""

#: English has two forms: singular and plural
PLURALS = {
    '%n item(s)': ['%n item', '%n items'],
    '%n downloaded': ['%n downloaded', '%n downloaded'],
    '%n failed': ['%n failed', '%n failed'],
    'Attempts: %n': ['Attempt: %n', 'Attempts: %n'],
}

#: Every other text keeps its source wording
TRANSLATIONS: dict[str, str] = {}
