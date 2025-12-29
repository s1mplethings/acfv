from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from .artifact import compute_fingerprint, coerce_output, producer_record
from .planner import build_plan
from .registry import AdapterRegistry, ModuleRegistry
from .types import AdapterContext, ArtifactEnvelope, ArtifactType, ModuleContext, ModuleSpec, ProgressCallback
from .utils import hash_obj


class PipelineRunner:
    def __init__(
        self,
        module_registry: ModuleRegistry,
        adapter_registry: AdapterRegistry,
        store,
    ) -> None:
        self.module_registry = module_registry
        self.adapter_registry = adapter_registry
        self.store = store

    def run(
        self,
        goal_types: Iterable[ArtifactType],
        seed_payloads: Optional[Dict[ArtifactType, Any]] = None,
        seed_artifacts: Optional[Iterable[ArtifactEnvelope]] = None,
        params_by_module: Optional[Dict[str, Dict[str, Any]]] = None,
        params_by_adapter: Optional[Dict[str, Dict[str, Any]]] = None,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> Dict[ArtifactType, ArtifactEnvelope]:
        available: Dict[ArtifactType, ArtifactEnvelope] = {}

        if seed_artifacts:
            for env in seed_artifacts:
                self.store.write_artifact(env)
                available[env.type] = env

        if seed_payloads:
            for art_type, payload in seed_payloads.items():
                params_hash = hash_obj({"seed": art_type})
                producer = producer_record("seed", "0", params_hash)
                env = ArtifactEnvelope(artifact_id="seed-" + params_hash, type=art_type, payload=payload)
                env.producer = producer
                env.fingerprint = params_hash
                self.store.write_artifact(env)
                available[art_type] = env

        plan = build_plan(list(goal_types), self.module_registry, available.keys())

        for step in plan:
            spec = step.module
            params = dict(spec.default_params)
            if params_by_module and spec.name in params_by_module:
                params.update(params_by_module[spec.name])

            inputs = self._resolve_inputs(spec, available, params_by_adapter or {}, progress_callback)
            fingerprint = compute_fingerprint(spec.name, spec.version, params, inputs)

            cached = self._load_cached_outputs(spec, fingerprint)
            if cached:
                available.update(cached)
                continue

            ctx = ModuleContext(
                inputs=inputs,
                params=params,
                store=self.store,
                run_id=self.store.run_dir.name,
                progress=progress_callback,
            )
            outputs = spec.run(ctx)

            produced = self._store_outputs(spec, outputs, inputs, params, fingerprint)
            available.update(produced)

        results: Dict[ArtifactType, ArtifactEnvelope] = {}
        for goal in goal_types:
            env = available.get(goal) or self.store.get_latest_by_type(goal)
            if env is None:
                raise RuntimeError(f"Goal not produced: {goal}")
            results[goal] = env
        return results

    def _resolve_inputs(
        self,
        spec: ModuleSpec,
        available: Dict[ArtifactType, ArtifactEnvelope],
        params_by_adapter: Dict[str, Dict[str, Any]],
        progress_callback: Optional[ProgressCallback],
    ) -> Dict[ArtifactType, ArtifactEnvelope]:
        resolved: Dict[ArtifactType, ArtifactEnvelope] = {}
        for art_type in spec.inputs:
            env = available.get(art_type) or self.store.get_latest_by_type(art_type)
            if env is None:
                env = self._apply_adapter(art_type, available, params_by_adapter, progress_callback)
            if env is None:
                raise RuntimeError(f"Missing required artifact: {art_type} for module {spec.name}")
            resolved[art_type] = env
            available[art_type] = env
        return resolved

    def _apply_adapter(
        self,
        target_type: ArtifactType,
        available: Dict[ArtifactType, ArtifactEnvelope],
        params_by_adapter: Dict[str, Dict[str, Any]],
        progress_callback: Optional[ProgressCallback],
    ) -> Optional[ArtifactEnvelope]:
        adapter = self.adapter_registry.find_adapter(target_type, available.keys())
        if adapter is None:
            return None

        source_env = available.get(adapter.source_type) or self.store.get_latest_by_type(adapter.source_type)
        if source_env is None:
            return None

        params = params_by_adapter.get(adapter.name, {})
        fingerprint = compute_fingerprint(adapter.name, adapter.version, params, {adapter.source_type: source_env})
        cached = self._load_cached_adapter_output(adapter.name, target_type, fingerprint)
        if cached:
            available[target_type] = cached
            return cached

        ctx = AdapterContext(
            source=source_env,
            params=params,
            store=self.store,
            run_id=self.store.run_dir.name,
            progress=progress_callback,
        )
        output = adapter.run(ctx)
        producer = producer_record(adapter.name, adapter.version, hash_obj(params))
        env = coerce_output(
            target_type,
            output,
            producer=producer,
            fingerprint=fingerprint,
            depends_on=[source_env.artifact_id],
        )
        self.store.write_artifact(env)
        available[target_type] = env
        return env

    def _load_cached_outputs(self, spec: ModuleSpec, fingerprint: str) -> Optional[Dict[ArtifactType, ArtifactEnvelope]]:
        cached = self.store.find_by_producer_fingerprint(spec.name, fingerprint)
        if not cached:
            return None
        by_type: Dict[ArtifactType, ArtifactEnvelope] = {}
        for env in cached:
            by_type[env.type] = env
        if not all(out in by_type for out in spec.outputs):
            return None
        return by_type

    def _load_cached_adapter_output(
        self, adapter_name: str, target_type: ArtifactType, fingerprint: str
    ) -> Optional[ArtifactEnvelope]:
        cached = self.store.find_by_producer_fingerprint(adapter_name, fingerprint)
        for env in cached:
            if env.type == target_type:
                return env
        return None

    def _store_outputs(
        self,
        spec: ModuleSpec,
        outputs: Dict[ArtifactType, Any],
        inputs: Dict[ArtifactType, ArtifactEnvelope],
        params: Dict[str, Any],
        fingerprint: str,
    ) -> Dict[ArtifactType, ArtifactEnvelope]:
        if outputs is None:
            raise RuntimeError(f"Module {spec.name} returned no outputs")

        produced: Dict[ArtifactType, ArtifactEnvelope] = {}
        params_hash = hash_obj(params)
        producer = producer_record(spec.name, spec.version, params_hash)
        depends_on = [env.artifact_id for env in inputs.values()]

        for art_type in spec.outputs:
            if art_type not in outputs:
                raise RuntimeError(f"Module {spec.name} missing output: {art_type}")
            env = coerce_output(
                art_type,
                outputs[art_type],
                producer=producer,
                fingerprint=fingerprint,
                depends_on=depends_on,
            )
            self.store.write_artifact(env)
            produced[art_type] = env
        return produced


__all__ = ["PipelineRunner"]
