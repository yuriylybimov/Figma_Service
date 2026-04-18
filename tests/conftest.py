"""Shared pytest fixtures for Figma_Service host-side tests."""
import sys
from pathlib import Path

# Make run.py importable as `run` from tests.
sys.path.insert(0, str(Path(__file__).parent.parent))
