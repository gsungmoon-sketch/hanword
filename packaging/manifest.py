"""Single source of the runtime Python modules for every build path
(packaging/build.py = PyInstaller binary, scripts/build_zipapp.py = .pyz, packaging/smoke_test.py).

Every top-level *.py of the app root is a runtime module (the public tree carries nothing else there),
so a new module can never be left out of one build path again. Lazily imported converters
(hanword_keep, hanword_embed, ...) are included the same way.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI_SCRIPT = "hanword"          # the extension-less CLI script (run via runpy)


def modules(root: Path = ROOT) -> list:
    """Module names (no .py), sorted. Fails if the version module is missing (public overlay)."""
    mods = sorted(p.stem for p in Path(root).glob("*.py") if p.is_file())
    if "hanword_version" not in mods and (Path(root) / "packaging" / "public-overlay" / "hanword_version.py").is_file():
        mods = sorted(mods + ["hanword_version"])   # dev tree: overlay supplies it in the public copy
    return mods
