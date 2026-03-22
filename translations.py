_STRINGS = {
    "en": {
        "title": "AI Image & Video Generator",
        "prompt_label": "Prompt",
        "upload_label": "Upload Image (optional)",
        "generate_image": "Generate Image",
        "generate_video": "Generate Video",
        "generating": "Generating… please wait.",
        "download": "Download",
        "try_again": "Try Again",
        "error_generic": "Something went wrong. Please try again.",
        "lang_switch": "Deutsch",
        "lang_switch_target": "de",
    },
    "de": {
        "title": "KI-Bild- & Videogenerator",
        "prompt_label": "Beschreibung",
        "upload_label": "Bild hochladen (optional)",
        "generate_image": "Bild generieren",
        "generate_video": "Video generieren",
        "generating": "Wird generiert… bitte warten.",
        "download": "Herunterladen",
        "try_again": "Nochmals versuchen",
        "error_generic": "Ein Fehler ist aufgetreten. Bitte erneut versuchen.",
        "lang_switch": "English",
        "lang_switch_target": "en",
    },
}


def get_strings(lang: str) -> dict:
    return _STRINGS.get(lang, _STRINGS["en"])
