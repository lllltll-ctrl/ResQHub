"""
Compatibility shim для backward compat з services/forecast_engine.
"""

from app.services.forecast_engine import ForecastResult, TelemetryPoint

__all__ = ["ForecastResult", "TelemetryPoint"]
