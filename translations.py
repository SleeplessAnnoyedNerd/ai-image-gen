_STRINGS = {
    "en": {
        "title": "AI Image & Video Generator",
        "prompt_label": "Prompt",
        "upload_label": "Upload Image (optional)",
        "generate_image": "Generate Image",
        "generate_video": "Generate Video",
        "generate_sd": "Stable Diffusion",
        "sd_checking": "Stable Diffusion (checking…)",
        "sd_offline":  "Stable Diffusion (offline)",
        "generating": "Generating… please wait.",
        "progress_queued": "Queue position: {}",
        "progress_running": "Processing…",
        "download": "Download",
        "try_again": "Try Again",
        "save_to_photos": "Save to Photos",
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
        "generate_sd": "Stable Diffusion",
        "sd_checking": "Stable Diffusion (wird geprüft…)",
        "sd_offline":  "Stable Diffusion (offline)",
        "generating": "Wird generiert… bitte warten.",
        "progress_queued": "Position in der Warteschlange: {}",
        "progress_running": "Wird verarbeitet…",
        "download": "Herunterladen",
        "try_again": "Nochmals versuchen",
        "save_to_photos": "In Fotos speichern",
        "error_generic": "Ein Fehler ist aufgetreten. Bitte erneut versuchen.",
        "lang_switch": "English",
        "lang_switch_target": "en",
    },
}


def get_strings(lang: str) -> dict:
    return _STRINGS.get(lang, _STRINGS["en"])
