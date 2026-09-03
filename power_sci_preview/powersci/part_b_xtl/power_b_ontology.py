from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping, Tuple

Dimension = Tuple[Tuple[str, int], ...]


@dataclass(frozen=True)
class VariableSpec:
    name: str
    symbol: str
    unit: str
    per_unit: bool
    coordinate: str
    role: str
    description: str
    reference_mode: str = 'NOT_APPLICABLE'
    nominal_value: float | int | None = None
    dimension: Dimension = ()


def _dim(*pairs: tuple[str, int]) -> Dimension:
    return tuple(sorted((axis, exp) for axis, exp in pairs if exp))


def build_default_variable_registry() -> Dict[str, VariableSpec]:
    items = [
        VariableSpec('delta', 'delta', 'rad', False, 'state', 'state', 'Rotor angle', 'ABSOLUTE', 0.0, _dim(('angle', 1))),
        VariableSpec('omega', 'omega', 'pu', True, 'state', 'state', 'Rotor speed', 'ABSOLUTE', 1.0, _dim(('speed', 1))),
        VariableSpec('d_delta_dt', 'd_delta_dt', 'rad/s', False, 'state', 'derivative', 'Rotor angle derivative', 'DEVIATION', 0.0, _dim(('angle', 1), ('time', -1))),
        VariableSpec('d_omega_dt', 'd_omega_dt', 'pu/s', True, 'state', 'derivative', 'Rotor speed derivative', 'DEVIATION', 0.0, _dim(('speed', 1), ('time', -1))),
        VariableSpec('Pm', 'Pm', 'pu', True, 'algebraic', 'input', 'Mechanical power', 'NOT_APPLICABLE', None, _dim(('power', 1))),
        VariableSpec('Pe', 'Pe', 'pu', True, 'algebraic', 'output', 'Electrical air-gap power', 'NOT_APPLICABLE', None, _dim(('power', 1))),
        VariableSpec('Pm_ref', 'Pm_ref', 'pu', True, 'parameter', 'parameter', 'Reference mechanical power', _dim(('power', 1))),
        VariableSpec('V', 'V', 'pu', True, 'algebraic', 'output', 'Terminal voltage magnitude', 'ABSOLUTE', 1.0, _dim(('voltage', 1))),
        VariableSpec('V_ref', 'V_ref', 'pu', True, 'parameter', 'parameter', 'Reference voltage magnitude', 'ABSOLUTE', 1.0, _dim(('voltage', 1))),
        VariableSpec('E', 'E', 'pu', True, 'parameter', 'parameter', 'Internal emf magnitude', 'ABSOLUTE', None, _dim(('voltage', 1))),
        VariableSpec('X', 'X', 'pu', True, 'parameter', 'parameter', 'Transfer reactance', 'NOT_APPLICABLE', None, _dim(('reactance', 1))),
        VariableSpec('H', 'H', 's', False, 'parameter', 'parameter', 'Inertia constant', 'NOT_APPLICABLE', None, _dim(('time', 1))),
        VariableSpec('D', 'D', 'pu', True, 'parameter', 'parameter', 'Damping coefficient', 'NOT_APPLICABLE', None, _dim(('power', 1))),
        VariableSpec('omega_b', 'omega_b', 'rad/s', False, 'parameter', 'parameter', 'Base electrical speed', 'NOT_APPLICABLE', 377.0, _dim(('time', -1))),
        VariableSpec('theta', 'theta', 'rad', False, 'algebraic', 'network', 'Voltage angle', 'ABSOLUTE', 0.0, _dim(('angle', 1))),
        VariableSpec('Id', 'Id', 'pu', True, 'algebraic', 'network', 'd-axis current', _dim(('current', 1))),
        VariableSpec('Iq', 'Iq', 'pu', True, 'algebraic', 'network', 'q-axis current', _dim(('current', 1))),
        VariableSpec('Ed', 'Ed', 'pu', True, 'algebraic', 'network', 'd-axis transient emf', _dim(('voltage', 1))),
        VariableSpec('Eq', 'Eq', 'pu', True, 'algebraic', 'network', 'q-axis transient emf', _dim(('voltage', 1))),
        VariableSpec('P', 'P', 'pu', True, 'algebraic', 'network', 'Active power injection', _dim(('power', 1))),
        VariableSpec('Q', 'Q', 'pu', True, 'algebraic', 'network', 'Reactive power injection', _dim(('power', 1))),
        VariableSpec('G', 'G', 'pu', True, 'parameter', 'parameter', 'Conductance', _dim(('admittance', 1))),
        VariableSpec('B', 'B', 'pu', True, 'parameter', 'parameter', 'Susceptance', _dim(('admittance', 1))),
        VariableSpec('Ybus', 'Ybus', 'pu', True, 'network', 'parameter', 'Network admittance matrix', _dim(('admittance', 1))),
        VariableSpec('Va', 'Va', 'rad', False, 'algebraic', 'network', 'Bus voltage angle', 'ABSOLUTE', 0.0, _dim(('angle', 1))),
        VariableSpec('Vm', 'Vm', 'pu', True, 'algebraic', 'network', 'Bus voltage magnitude', 'ABSOLUTE', 1.0, _dim(('voltage', 1))),
        VariableSpec('P_load', 'P_load', 'pu', True, 'parameter', 'input', 'Active load demand', 'NOT_APPLICABLE', None, _dim(('power', 1))),
        VariableSpec('Q_load', 'Q_load', 'pu', True, 'parameter', 'input', 'Reactive load demand', 'NOT_APPLICABLE', None, _dim(('power', 1))),
        VariableSpec('P_gen', 'P_gen', 'pu', True, 'parameter', 'input', 'Generated active power', 'NOT_APPLICABLE', None, _dim(('power', 1))),
        VariableSpec('Q_gen', 'Q_gen', 'pu', True, 'parameter', 'input', 'Generated reactive power', 'NOT_APPLICABLE', None, _dim(('power', 1))),
        VariableSpec('M', 'M', 's', False, 'parameter', 'parameter', 'Swing equation mass term', 'NOT_APPLICABLE', None, _dim(('time', 1))),
        VariableSpec('omega_syn', 'omega_syn', 'rad/s', False, 'parameter', 'parameter', 'Synchronous speed', 'ABSOLUTE', 377.0, _dim(('time', -1))),
        VariableSpec('delta_ref', 'delta_ref', 'rad', False, 'parameter', 'parameter', 'Reference rotor angle', 'ABSOLUTE', 0.0, _dim(('angle', 1))),
        VariableSpec('P_elec', 'P_elec', 'pu', True, 'algebraic', 'output', 'Alias for electrical power', 'NOT_APPLICABLE', None, _dim(('power', 1))),
        VariableSpec('V_bus', 'V_bus', 'pu', True, 'algebraic', 'network', 'Bus voltage magnitude', 'ABSOLUTE', 1.0, _dim(('voltage', 1))),
        VariableSpec('theta_bus', 'theta_bus', 'rad', False, 'algebraic', 'network', 'Bus voltage angle', 'ABSOLUTE', 0.0, _dim(('angle', 1))),
        VariableSpec('omega_dev', 'omega_dev', 'pu', True, 'state', 'state', 'Speed deviation from nominal', 'DEVIATION', 0.0, _dim(('speed', 1))),
        VariableSpec('t', 't', 's', False, 'time', 'parameter', 'Time variable', 'NOT_APPLICABLE', None, _dim(('time', 1))),
    ]
    return {item.name: item for item in items}


DEFAULT_VARIABLE_REGISTRY = build_default_variable_registry()


def lookup_variable_spec(name: str, registry: Mapping[str, VariableSpec] | None = None) -> VariableSpec:
    source = registry or DEFAULT_VARIABLE_REGISTRY
    if name not in source:
        raise KeyError(f'Unknown variable spec: {name}')
    return source[name]
