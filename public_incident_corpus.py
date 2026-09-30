from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True, slots=True)
class PublicIncident:
    case_id: str
    repository: str
    source_url: str
    observed_signal: str
    actual_cause_family: str
    remediation_family: str
    classifier_implication: str
    expected_decision: str = "BLOCK"
    ground_truth_run_id: int | None = None
    failed_job_id: int | None = None
    successful_rerun_job_id: int | None = None
    recurrent_rerun_job_id: int | None = None


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


ALUNDUIL_CURL_RESET = PublicIncident(
    case_id="alunduil-chezmoi-curl-reset-2026-07-27",
    repository="alunduil/alunduil-chezmoi",
    source_url="https://github.com/alunduil/alunduil-chezmoi/issues/473",
    observed_signal="curl: (35) Recv failure: Connection reset by peer",
    actual_cause_family="TRANSIENT_DEPENDENCY_NETWORK",
    remediation_family="RETRY_TRANSIENT_DOWNLOAD",
    classifier_implication=(
        "A connection reset emitted by curl inside the failed install step is "
        "direct transient-network evidence when execution provenance is confirmed."
    ),
    expected_decision="ALLOW",
    ground_truth_run_id=30240791215,
    failed_job_id=89897364311,
    successful_rerun_job_id=90214160124,
)


UZI_CURL_RESET = PublicIncident(
    case_id="uzi-curl-reset-2026-09-05",
    repository="vtmocanu/uzi",
    source_url="https://github.com/vtmocanu/uzi/issues/1144",
    observed_signal="curl: (35) Recv failure: Connection reset by peer",
    actual_cause_family="TRANSIENT_DEPENDENCY_NETWORK",
    remediation_family="RETRY_TRANSIENT_DOWNLOAD",
    classifier_implication=(
        "A connection reset during the failed lint download step can justify a "
        "bounded retry when the same SHA succeeds on the next workflow attempt."
    ),
    expected_decision="ALLOW",
    ground_truth_run_id=33985176395,
    failed_job_id=101357253123,
    successful_rerun_job_id=101358255354,
)


DOCKER_COMPOSE_REGISTRY_502 = PublicIncident(
    case_id="docker-compose-registry-502-2026-09-16",
    repository="docker/compose",
    source_url="https://github.com/docker/compose/actions/runs/35155815118",
    observed_signal="Docker registry HEAD request returned 502 Bad Gateway",
    actual_cause_family="TRANSIENT_DEPENDENCY_NETWORK",
    remediation_family="BOUNDED_RERUN_AFTER_REGISTRY_5XX",
    classifier_implication=(
        "Repeated causal 502 responses from the external registry inside the failed "
        "build step support a high-confidence dependency-network classification."
    ),
    expected_decision="ALLOW",
    ground_truth_run_id=35155815118,
    failed_job_id=104994979798,
    successful_rerun_job_id=104997281020,
)


ALETHIALABS_NETWORK_UNREACHABLE = PublicIncident(
    case_id="alethialabs-helm-network-unreachable-2026-08-26",
    repository="alethialabs-io/alethialabs",
    source_url="https://github.com/alethialabs-io/alethialabs/issues/2754",
    observed_signal="dial tcp ... connect: network is unreachable while fetching a Helm repository",
    actual_cause_family="TRANSIENT_DEPENDENCY_NETWORK",
    remediation_family="BOUNDED_RERUN_AFTER_NETWORK_UNREACHABLE",
    classifier_implication=(
        "A timestamped dial-tcp network-unreachable error inside the failed fetch/render "
        "step is direct dependency-network evidence when the same job later succeeds."
    ),
    expected_decision="ALLOW",
    ground_truth_run_id=32938269387,
    failed_job_id=98083760153,
    successful_rerun_job_id=98086599142,
)


PRQL_HOSTED_RUNNER_LOSS = PublicIncident(
    case_id="prql-hosted-runner-loss-2026-08-26",
    repository="PRQL/prql",
    source_url="https://github.com/PRQL/prql/issues/6236",
    observed_signal="The hosted runner lost communication with the server",
    actual_cause_family="HOSTED_RUNNER_LOSS",
    remediation_family="RERUN_FAILED_JOB",
    classifier_implication=(
        "A later diagnosis may identify runner loss, but automatic authority still requires "
        "decision-time evidence bound to the failed execution. Missing logs/step provenance "
        "must fail closed until an authenticated annotation evidence path exists."
    ),
    expected_decision="BLOCK",
    ground_truth_run_id=32960945674,
    failed_job_id=98152972844,
    successful_rerun_job_id=98168778451,
)


HIROMI_RATE_LIMIT_RECURRENCE = PublicIncident(
    case_id="hiromi-github-rate-limit-recurrence-2026-09-26",
    repository="HiromiShikata/npm-cli-github-issue-tower-defence-management",
    source_url="https://github.com/HiromiShikata/npm-cli-github-issue-tower-defence-management/issues/2768",
    observed_signal="GitHub API rate limit error in the failing Find associated pull request step",
    actual_cause_family="PERSISTENT_DEPENDENCY_RATE_LIMIT",
    remediation_family="FIX_RATE_LIMIT_ERROR_HANDLING",
    classifier_implication=(
        "A dependency-shaped rate-limit failure is not automatically retry-safe when the same "
        "job fails again on the next attempt with the same signature."
    ),
    expected_decision="BLOCK",
    ground_truth_run_id=36248287482,
    failed_job_id=108421448279,
    successful_rerun_job_id=None,
    recurrent_rerun_job_id=108422710231,
)


PUBLIC_INCIDENT_CORPUS_V1 = (
    GEOPHIRES_526,
    DECK_STREAK_439,
    ONE_BIT_BRIDGE_1098,
)


PUBLIC_INCIDENT_CORPUS_V2 = PUBLIC_INCIDENT_CORPUS_V1 + (
    ALUNDUIL_CURL_RESET,
    UZI_CURL_RESET,
    DOCKER_COMPOSE_REGISTRY_502,
)


PUBLIC_INCIDENT_CORPUS_V3 = PUBLIC_INCIDENT_CORPUS_V2 + (
    ALETHIALABS_NETWORK_UNREACHABLE,
    PRQL_HOSTED_RUNNER_LOSS,
    HIROMI_RATE_LIMIT_RECURRENCE,
)


PRQL_HOSTED_RUNNER_LOSS_AUTHENTICATED = replace(
    PRQL_HOSTED_RUNNER_LOSS,
    classifier_implication=(
        "When the job log is unavailable, an authenticated GitHub Actions check-run "
        "failure annotation can supply missing job-bound runner-loss provenance if "
        "check-run id, job name, head SHA, conclusion, and app identity all bind exactly. "
        "That evidence does not override an independent side-effect boundary."
    ),
    expected_decision="BLOCK",
)


PUBLIC_INCIDENT_CORPUS_V4 = tuple(
    PRQL_HOSTED_RUNNER_LOSS_AUTHENTICATED
    if incident.case_id == PRQL_HOSTED_RUNNER_LOSS.case_id
    else incident
    for incident in PUBLIC_INCIDENT_CORPUS_V3
)
