"""
Central configuration for the analyzer.

This module is intentionally declarative: it captures the *domain knowledge* a
satellite AIT/CCS engineer would normally hold in a parameter database
(MIB-style): nominal values, soft (yellow) limits and hard (red) limits for
each monitored telemetry parameter, plus the list of subsystems that appear in
test logs.

Keeping limits here (instead of hard-coding them across the codebase) mirrors
how real Central Check-Out Systems separate the limit definition from the
monitoring logic, and makes the prototype easy to re-target to a different
spacecraft.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ParamLimits:
    """Limit definition for a single telemetry parameter (CCS-style)."""

    name: str
    unit: str
    nominal: float
    std: float            # nominal noise (used by the synthetic generator)
    yellow_low: float     # soft lower limit -> WARNING
    yellow_high: float    # soft upper limit -> WARNING
    red_low: float        # hard lower limit -> ALARM / out-of-limit (OOL)
    red_high: float       # hard upper limit -> ALARM / out-of-limit (OOL)
    description: str = ""

    def classify(self, value: float) -> str:
        """Return 'NOMINAL', 'YELLOW' or 'RED' for a single sample."""
        if value <= self.red_low or value >= self.red_high:
            return "RED"
        if value <= self.yellow_low or value >= self.yellow_high:
            return "YELLOW"
        return "NOMINAL"


# --- Monitored telemetry parameters -------------------------------------------------
# Representative subset of parameters monitored during a satellite functional /
# thermal-vacuum test campaign.
TELEMETRY_PARAMS: dict[str, ParamLimits] = {
    "eps_battery_voltage_v": ParamLimits(
        name="eps_battery_voltage_v", unit="V", nominal=28.0, std=0.05,
        yellow_low=27.2, yellow_high=29.2, red_low=26.5, red_high=29.8,
        description="Main battery bus voltage",
    ),
    "eps_bus_current_a": ParamLimits(
        name="eps_bus_current_a", unit="A", nominal=4.5, std=0.20,
        yellow_low=2.0, yellow_high=7.0, red_low=1.0, red_high=8.5,
        description="Primary power bus current draw",
    ),
    "tcs_panel_temp_c": ParamLimits(
        name="tcs_panel_temp_c", unit="degC", nominal=22.0, std=0.6,
        yellow_low=-10.0, yellow_high=45.0, red_low=-20.0, red_high=60.0,
        description="+Y radiator panel temperature",
    ),
    "tcs_obc_temp_c": ParamLimits(
        name="tcs_obc_temp_c", unit="degC", nominal=35.0, std=0.8,
        yellow_low=5.0, yellow_high=55.0, red_low=0.0, red_high=70.0,
        description="On-board computer board temperature",
    ),
    "aocs_rw_rpm": ParamLimits(
        name="aocs_rw_rpm", unit="rpm", nominal=2400.0, std=30.0,
        yellow_low=200.0, yellow_high=5800.0, red_low=0.0, red_high=6300.0,
        description="Reaction wheel #1 angular rate",
    ),
    "comms_rssi_dbm": ParamLimits(
        name="comms_rssi_dbm", unit="dBm", nominal=-65.0, std=2.0,
        yellow_low=-88.0, yellow_high=-45.0, red_low=-98.0, red_high=-35.0,
        description="S-band downlink received signal strength",
    ),
}


# --- Subsystems that emit log lines -------------------------------------------------
SUBSYSTEMS: list[str] = [
    "EPS",       # Electrical Power Subsystem
    "TCS",       # Thermal Control Subsystem
    "AOCS",      # Attitude & Orbit Control Subsystem
    "OBC",       # On-Board Computer
    "COMMS",     # Communications
    "PAYLOAD",   # Payload instrument
    "EGSE",      # Electrical Ground Support Equipment
    "CCS",       # Central Check-Out System
    "HARNESS",   # Test harness / interface
]

LOG_LEVELS: list[str] = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

# Severity ranking used for sorting / scoring.
LEVEL_SEVERITY: dict[str, int] = {
    "DEBUG": 0,
    "INFO": 1,
    "WARNING": 2,
    "ERROR": 3,
    "CRITICAL": 4,
}
