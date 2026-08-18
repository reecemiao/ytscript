"""ytscript — turn a YouTube channel's videos into plain-text scripts."""

from .config import Config, ConfigError, load_config
from .models import RunReport, Segment, Transcript, Video
from .pipeline import Pipeline
from .state import State

__version__ = "0.1.0"

__all__ = [
    "Config",
    "ConfigError",
    "Pipeline",
    "RunReport",
    "Segment",
    "State",
    "Transcript",
    "Video",
    "__version__",
    "load_config",
]
