from __future__ import annotations

from typing import Any, Dict, Optional
from uuid import uuid4

from .types import ArtifactEnvelope, ArtifactType
from .utils import hash_obj


def new_artifact_id() -> str:
    return uuid4().hex


def producer_record(name: str, version: str, params_hash: str) -> Dict[str, Any]:
    return {
        "name": name,
        "version": version,
        "params_hash": params_hash,
    }


def compute_fingerprint(
    module_name: str,
    module_version: str,
    params: Dict[str, Any],
    inputs: Dict[ArtifactType, ArtifactEnvelope],
) -> str:
    input_fingerprints = {
        art_type: (env.fingerprint or env.artifact_id)
        for art_type, env in sorted(inputs.items())
    }
    return hash_obj(
        {
            "module": module_name,
            "version": module_version,
            "params": params,
            "inputs": input_fingerprints,
        }
    )


def coerce_output(
    artifact_type: ArtifactType,
    output: Any,
    producer: Dict[str, Any],
    fingerprint: str,
    depends_on: Optional[list[str]] = None,
) -> ArtifactEnvelope:
    if isinstance(output, ArtifactEnvelope):
        env = output
        if env.type != artifact_type:
            raise ValueError(f"Output type mismatch: {env.type} != {artifact_type}")
        if not env.artifact_id:
            env.artifact_id = new_artifact_id()
    else:
        env = ArtifactEnvelope(
            artifact_id=new_artifact_id(),
            type=artifact_type,
            payload=output,
        )
    env.producer = producer
    env.fingerprint = fingerprint
    env.depends_on = list(depends_on or [])
    return env


__all__ = [
    "new_artifact_id",
    "producer_record",
    "compute_fingerprint",
    "coerce_output",
]
