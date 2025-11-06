from typing import List, Optional, Literal
from pydantic import BaseModel, Field


class ValueWithUnits(BaseModel):
    value: Optional[float] = None
    units: Optional[str] = None


class Concentration(BaseModel):
    value: Optional[float] = None
    units: Optional[str] = None  # M, mol/L, v/v%, wt%, etc.
    concentration_type: Optional[Literal["molar", "volume_percent", "weight_percent", "molal"]] = None


class ElectrolyteComponent(BaseModel):
    name: str
    concentration: Optional[Concentration] = None


class Electrolyte(BaseModel):
    components: List[ElectrolyteComponent] = Field(default_factory=list)


class PerformanceMetrics(BaseModel):
    # Performance metrics
    coulombic_efficiency: Optional[ValueWithUnits] = None  # %
    average_coulombic_efficiency: Optional[ValueWithUnits] = None  # %
    cycle_lifetime: Optional[ValueWithUnits] = None  # h
    cycle_count: Optional[ValueWithUnits] = None  # # cycles
    capacity_retention: Optional[ValueWithUnits] = None  # %

    # Capacity metrics
    specific_capacity: Optional[ValueWithUnits] = None  # mAh/g
    areal_capacity: Optional[ValueWithUnits] = None  # mAh/cm²

    # Energy density
    gravimetric_energy_density: Optional[ValueWithUnits] = None  # Wh/kg
    volumetric_energy_density: Optional[ValueWithUnits] = None  # Wh/L

    # Current and electrical properties
    current_density: Optional[ValueWithUnits] = None  # mA/cm²

    # Material properties
    ionic_conductivity: Optional[ValueWithUnits] = None  # S/cm
    electronic_conductivity: Optional[ValueWithUnits] = None  # S/cm
    transference_number: Optional[ValueWithUnits] = None  # dimensionless

    # Electrochemical properties
    electrochemical_stability_window: Optional[ValueWithUnits] = None  # V
    overpotential: Optional[ValueWithUnits] = None  # V
    voltage_range: Optional[ValueWithUnits] = None  # V
    average_working_voltage: Optional[ValueWithUnits] = None  # V
    impedance: Optional[ValueWithUnits] = None  # Ohm

    # Physical properties
    viscosity: Optional[ValueWithUnits] = None  # mPa·s
    diffusion_coefficient: Optional[ValueWithUnits] = None  # cm²/s


class Measurement(BaseModel):
    measurement_type: Literal["experimental", "computational"]
    performance_metrics: Optional[PerformanceMetrics] = None
    details: Optional[str] = None


class CellComponents(BaseModel):
    anode_material: str
    electrolyte: Electrolyte
    electrolyte_type: Literal["liquid", "solid", "quasi-solid"]
    separator: Optional[str] = None
    separator_type: Optional[Literal["polymer", "ceramic", "glass", "other"]] = None
    cathode_material: Optional[str] = None


class Temperature(BaseModel):
    control_type: Optional[str] = None
    value: Optional[float] = None
    units: Optional[str] = None


class Pressure(BaseModel):
    control_type: Optional[str] = None
    value: Optional[float] = None
    units: Optional[str] = None


class CyclingRate(BaseModel):
    control_type: Optional[str] = None
    value: Optional[float] = None
    units: Optional[str] = None


class GlobalConditions(BaseModel):
    temperature: Optional[Temperature] = None
    pressure: Optional[Pressure] = None
    conditions_are_dynamic: bool = False


class CellConditions(BaseModel):
    cycling_rate: Optional[CyclingRate] = None  # C
    conditions_are_dynamic: bool = False


class Cell(BaseModel):
    name: str
    measurements: List[Measurement] = Field(default_factory=list)
    cell_conditions: Optional[CellConditions] = None


class Outcome(BaseModel):
    cells: List[Cell] = Field(default_factory=list)
    global_conditions: GlobalConditions


class Battery(BaseModel):
    battery_type: Literal["lithium_sulphur", "lithium_air", "lithium_CO2", "lithium_metal"]
    cell_components: CellComponents
    outcomes: List[Outcome] = Field(default_factory=list)
