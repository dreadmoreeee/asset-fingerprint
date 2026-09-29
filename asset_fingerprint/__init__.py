"""Fingerprint static assets in a build folder and rewrite every reference."""

from .core import Config, Plan, apply_plan, build_plan

__version__ = "0.1.0"
__all__ = ["Config", "Plan", "apply_plan", "build_plan", "__version__"]
