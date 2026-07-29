# src/prediction_core/__init__.py
"""
Core prediction module for satellite visibility calculations.
This module handles both single and multiple satellite predictions with support for multiprocessing.
"""

from .predictor_gui import SatellitePredictor

__all__ = ["SatellitePredictor"]
