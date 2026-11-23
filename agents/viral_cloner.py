"""Bridge re-exporting VideoDNAExtractor and clone_viral_url from engine/viral_cloner.py."""
from engine.viral_cloner import VideoDNAExtractor, clone_viral_url

__all__ = ["VideoDNAExtractor", "clone_viral_url"]
