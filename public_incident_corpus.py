from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PublicIncident:
    case_id: str
    repository: str
    source_url: str
    observed_signal: str
    actual_cause_family: str
    remediation_family: str
    classifier_implication: str


GEOPHIRES_526 = PublicIncident(
    case_id="geophires-x-526-runner-shutdown",
    repository="NatLabRockies/GEOPHIRES-X",
    source_url="https://github.com/NatLabRockies/GEOPHIRES-X/issues/526",
    observed_signal="runner shutdown + exit 143 after tests reached 100%",
    actual_cause_family="WORKLOAD_RESOURCE_PRESSURE",
    remediation_family="REDUCE_MEMORY_RETENTION",
    classifier_implication=(
        "Runner shutdown is a terminal symptom and must not independently grant "
        "high-confidence RUNNER_INFRA."
    ),
)

DECK_STREAK_439 = PublicIncident(
    case_id="deck-streak-439-runaway-mutant",
    repository="RexRenatus/deck-streak",
    source_url="https://github.com/RexRenatus/deck-streak/issues/439",
    observed_signal="runner shutdown while mutation test was executing",
    actual_cause_family="RUNAWAY_PROCESS_MEMORY_GROWTH",
    remediation_family="BOUND_PROCESS_MEMORY_SCOPE",
    classifier_implication=(
        "Repeated shutdown on the same workload identity is evidence against a "
        "blind infrastructure-transient assumption."
    ),
)

ONE_BIT_BRIDGE_1098 = PublicIncident(
    case_id="1-bit-bridge-1098-fuzz-oom",
    repository="acoseac/1-bit-bridge",
    source_url="https://github.com/acoseac/1-bit-bridge/pull/1098",
    observed_signal="runner shutdown + exit 143 during fuzzing",
    actual_cause_family="INPUT_DRIVEN_MEMORY_EXHAUSTION",
    remediation_family="ALLOCATION_GUARD_AND_ADDRESS_SPACE_LIMIT",
    classifier_implication=(
        "A runner terminal signal can be downstream of an application OOM and "
        "therefore cannot prove runner infrastructure causality by itself."
    ),
)


PUBLIC_INCIDENT_CORPUS_V1 = (
    GEOPHIRES_526,
    DECK_STREAK_439,
    ONE_BIT_BRIDGE_1098,
)
