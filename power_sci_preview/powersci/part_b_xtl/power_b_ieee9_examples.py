from __future__ import annotations

from .power_b_equation_ir import CandidateModel, EquationNode, ParameterRef, VariableRef


def build_ieee9_placeholder_model() -> CandidateModel:
    return CandidateModel(
        candidate_id='ieee9_placeholder',
        model_name='IEEE 9 Dynamic Network Placeholder',
        variables=[
            VariableRef('delta', 'delta', 'rad'),
            VariableRef('omega', 'omega', 'pu'),
            VariableRef('Vm', 'Vm', 'pu'),
            VariableRef('Va', 'Va', 'rad'),
            VariableRef('P', 'P', 'pu'),
            VariableRef('Q', 'Q', 'pu'),
        ],
        parameters=[
            ParameterRef('H', 3.5, 's'),
            ParameterRef('D', 0.1, 'pu'),
            ParameterRef('Ybus', None, 'pu'),
        ],
        equations=[
            EquationNode(kind='residual', lhs='0', rhs='P_gen - P_load - P_network', unit='balance', expression='P_gen - P_load - P'),
            EquationNode(kind='residual', lhs='0', rhs='Q_gen - Q_load - Q_network', unit='balance', expression='Q_gen - Q_load - Q'),
        ],
        metadata={'status': 'placeholder', 'note': 'Replace residuals with full IEEE 9 bus network equations when C part publishes CaseManifest.'},
    )
