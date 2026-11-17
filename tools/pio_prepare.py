"""Refresh PlatformIO's cached component list when configuring ESP-IDF."""
from pathlib import Path

Import("env")
project = Path(env.subst("$PROJECT_DIR")).resolve()
cache = Path(env.subst("$BUILD_DIR")) / "ldgen_libraries_pio"
if cache.resolve().is_relative_to(project):
    cache.unlink(missing_ok=True)
