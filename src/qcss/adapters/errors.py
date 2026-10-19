"""gRPC error mapping with rich google.rpc.Status details."""
from __future__ import annotations

import grpc
from google.rpc import code_pb2, error_details_pb2, status_pb2
from grpc_status import rpc_status

from qcss.core.errors import HardwareValidationError


def invalid_argument_status(err: HardwareValidationError) -> grpc.Status:
    br = error_details_pb2.BadRequest(
        field_violations=[
            error_details_pb2.BadRequest.FieldViolation(field=p, description=d)
            for p, d in err.violations
        ]
    )
    st = status_pb2.Status(code=code_pb2.INVALID_ARGUMENT, message=str(err)[:1000])
    st.details.add().Pack(br)
    return rpc_status.to_status(st)


def failed_precondition_status(kind: str, subject: str, description: str) -> grpc.Status:
    """Tier routing refusals and stale calibration epochs (the job is valid, the system state is not)."""
    pf = error_details_pb2.PreconditionFailure(
        violations=[error_details_pb2.PreconditionFailure.Violation(type=kind, subject=subject,
                                                                    description=description[:1000])])
    st = status_pb2.Status(code=code_pb2.FAILED_PRECONDITION, message=description[:1000])
    st.details.add().Pack(pf)
    return rpc_status.to_status(st)
