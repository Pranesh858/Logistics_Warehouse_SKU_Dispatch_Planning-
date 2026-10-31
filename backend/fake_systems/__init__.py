"""A stand-in WMS and ERP that speak real HTTP, for testing the planner's integration code end to end.

Standalone on purpose: nothing here imports `app`. It shares only the seed CSV files, the way a real external
system shares data with the planner and not code. See fake_systems/README.md.
"""
from fake_systems.server import create_app

__all__ = ["create_app"]
