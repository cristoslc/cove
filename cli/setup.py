"""Build script — syncs compose resources before building the wheel."""

import subprocess
import sys
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py


class BuildPyWithSync(build_py):
    def run(self):
        script = Path(__file__).resolve().parent / "scripts" / "sync_compose_resources.py"
        if script.exists():
            subprocess.run([sys.executable, str(script)], check=True)
        super().run()


setup(cmdclass={"build_py": BuildPyWithSync})
