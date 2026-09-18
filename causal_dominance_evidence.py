from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Server5xxEvidenceCase:
    wave: int
    repository: str
    run_id: int
    job_name: str
    runtime_category: str
    recovery_status: str
    side_effect_risk: bool


# Immutable ledger reconstructed from the three completed SERVER_5XX evidence waves.
# These are Ground-Truth-evaluable causal SERVER_5XX recoveries. They are evidence
# for the mechanism family, not all causal-dominance positive controls.
VALIDATED_SERVER5XX_EVIDENCE = (
    Server5xxEvidenceCase(
        1,
        "docker/compose",
        35155815118,
        "relay-image-test / build (0, linux/amd64, ubuntu-24.04)",
        "DEPENDENCY_NETWORK",
        "VALIDATED_RECOVERY",
        True,
    ),
    Server5xxEvidenceCase(
        1,
        "docker/compose",
        35155815118,
        "relay-image-test / build (3, linux/arm64, ubuntu-24.04)",
        "DEPENDENCY_NETWORK",
        "VALIDATED_RECOVERY",
        True,
    ),
    Server5xxEvidenceCase(
        1,
        "serde-rs/serde",
        34427119351,
        "Outdated",
        "UNKNOWN",
        "VALIDATED_RECOVERY",
        False,
    ),
    Server5xxEvidenceCase(
        1,
        "traefik/traefik",
        34857150924,
        "lint",
        "UNKNOWN",
        "VALIDATED_RECOVERY",
        False,
    ),
    Server5xxEvidenceCase(
        2,
        "zed-industries/zed",
        35287790144,
        "check_workspace_binaries",
        "UNKNOWN",
        "VALIDATED_RECOVERY",
        False,
    ),
    Server5xxEvidenceCase(
        3,
        "kubernetes-sigs/kustomize",
        33608801087,
        "Test ubuntu-latest - api",
        "RUNNER_INFRA",
        "VALIDATED_RECOVERY",
        False,
    ),
    Server5xxEvidenceCase(
        3,
        "pulumi/pulumi",
        33615054816,
        "CI / Acceptance Test / tests/integration 6/8 on windows-latest/current",
        "RUNNER_INFRA",
        "VALIDATED_RECOVERY",
        True,
    ),
    Server5xxEvidenceCase(
        3,
        "swc-project/swc",
        34857087554,
        "Benchmark swc_html_parser",
        "UNKNOWN",
        "VALIDATED_RECOVERY",
        False,
    ),
    Server5xxEvidenceCase(
        3,
        "swc-project/swc",
        34857087636,
        "Test - swc - macos-latest",
        "CODE_REGRESSION",
        "VALIDATED_RECOVERY",
        True,
    ),
    Server5xxEvidenceCase(
        3,
        "swc-project/swc",
        34857087636,
        "Test wasm (binding_minifier_wasm)",
        "UNKNOWN",
        "VALIDATED_RECOVERY",
        True,
    ),
    Server5xxEvidenceCase(
        3,
        "swc-project/swc",
        34857087719,
        "Measure Binary Size",
        "UNKNOWN",
        "VALIDATED_RECOVERY",
        False,
    ),
)


# A separate contradiction was observed in Wave 3 but did not have a
# ground-truth-evaluable rerun outcome, so it is intentionally excluded from
# the 11 validated recoveries above.
UNEVALUATED_CLASSIFICATION_CONTRADICTIONS = (
    (
        "hashicorp/consul",
        34451868823,
        "envoy-integration-test (client, 1.36.8, ...)",
        "FLAKY_TEST",
        "NOT_OBSERVED",
    ),
)
