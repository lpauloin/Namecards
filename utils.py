import sys
from pathlib import Path


def resource_path(relative: str) -> Path:
    """
    Return absolute path to resource, works for dev and PyInstaller.
    """
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / relative
    return Path(__file__).parent / relative
