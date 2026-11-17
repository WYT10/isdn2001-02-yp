"""Use these lines in PythonAnywhere's Web-tab WSGI configuration."""
import sys
from pathlib import Path

project = str(Path.home() / "mysite")
if project not in sys.path:
    sys.path.insert(0, project)

from flask_app import app as application
