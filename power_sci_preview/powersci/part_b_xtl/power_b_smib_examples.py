from __future__ import annotations

from .power_b_equation_ir import CandidateModel, EquationNode, ParameterRef, VariableRef


def build_smib_correct_model() -> CandidateModel:
    return CandidateModel(
        candidate_id='smib_correct',
        model_name='SMIB Swing Equation',
        variables=[
            VariableRef('delta', 'delta', 'rad', 'rotor_angle', 'ABSOLUTE', 0.0),
            VariableRef('omega', 'omega', 'pu', 'rotor_speed', 'ABSOLUTE', 1.0),
            VariableRef('Pm', 'Pm', 'pu', 'generator_power', 'NOT_APPLICABLE', None),
            VariableRef('Pe', 'Pe', 'pu', 'generator_power', 'NOT_APPLICABLE', None),
        ],
        parameters=[
            ParameterRef('H', 3.5, 's'),
            ParameterRef('D', 0.1, 'pu'),
            ParameterRef('omega_b', 377.0, 'rad/s'),
        ],
        equations=[
            EquationNode(kind='ode', lhs='d(delta)/dt', rhs='omega_b * (omega - 1)', unit='rate', expression='d(delta)/dt - omega_b * (omega - 1)', equation_id='eq-001'),
            EquationNode(kind='ode', lhs='d(omega)/dt', rhs='(Pm - Pe - D*(omega - 1)) / (2*H)', unit='rate', expression='d(omega)/dt - (Pm - Pe - D*(omega - 1)) / (2*H)', equation_id='eq-002'),
            EquationNode(kind='algebraic', lhs='0', rhs='Pe - (Pm)', unit='balance', expression='Pe - Pm', equation_id='eq-003'),
        ],
    )


def build_smib_power_violation_model() -> CandidateModel:
    model = build_smib_correct_model()
    return CandidateModel(
        candidate_id='smib_power_violation',
        model_name='SMIB Power Violation',
        variables=list(model.variables),
        parameters=list(model.parameters),
        equations=[
            EquationNode(kind='ode', lhs='d(delta)/dt', rhs='omega_b * (omega - 1)', unit='rate', expression='d(delta)/dt - omega_b * (omega - 1)', equation_id='eq-001'),
            EquationNode(kind='ode', lhs='d(omega)/dt', rhs='(Pm - D*(omega - 1)) / (2*H)', unit='rate', expression='d(omega)/dt - (Pm - D*(omega - 1)) / (2*H)', equation_id='eq-002'),
            EquationNode(kind='algebraic', lhs='0', rhs='Pm', unit='balance', expression='Pm', equation_id='eq-003'),
        ],
    )


def build_smib_missing_closure_model() -> CandidateModel:
    model = build_smib_correct_model()
    return CandidateModel(
        candidate_id='smib_missing_closure',
        model_name='SMIB Missing Closure',
        variables=list(model.variables),
        parameters=list(model.parameters),
        equations=[
            EquationNode(kind='ode', lhs='d(delta)/dt', rhs='omega_b * (omega - 1)', unit='rate', expression='d(delta)/dt - omega_b * (omega - 1)', equation_id='eq-001'),
            EquationNode(kind='ode', lhs='d(omega)/dt', rhs='(Pm - Pe - D*(omega - 1)) / (2*H)', unit='rate', expression='d(omega)/dt - (Pm - Pe - D*(omega - 1)) / (2*H)', equation_id='eq-002'),
        ],
    )
