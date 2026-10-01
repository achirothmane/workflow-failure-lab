// Pure deterministic decisions. No I/O, model judgment, randomness, or wall clock.
export const DEFAULT_POLICY = Object.freeze({
  stages: [5, 25, 50, 100],
  minCandidate: 200, minStable: 200, minStageMs: 300000,
  healthyWindows: 2, freshBatch: 100, windowMs: 1800000,
  maxErrorRate: 0.02, maxErrorDelta: 0.02, maxInvalidRate: 0,
  maxP95Ms: 3000, maxLatencyRatio: 1.5, latencySlackMs: 100,
  earlyMin: 20, maxCandidateFailures: 5, earlyErrorRate: 0.10, maxStableErrorRate: 0.05,
  maxStableP95Ms: 5000, minCompleteness: 1, maxMetricAgeMs: 60000,
  requestTimeoutMs: 10000, leaseMs: 30000, baselineProbePct: 10
});

export function policy(input = {}) {
  if (!input || Array.isArray(input) || typeof input !== 'object') throw Error('policy must be an object');
  for (const k of Object.keys(input)) if (!(k in DEFAULT_POLICY)) throw Error('unknown policy: ' + k);
  const p = { ...DEFAULT_POLICY, ...input };
  const ints = ['minCandidate','minStable','minStageMs','healthyWindows','freshBatch',
    'windowMs','maxP95Ms','latencySlackMs','earlyMin','maxCandidateFailures','maxStableP95Ms','maxMetricAgeMs',
    'requestTimeoutMs','leaseMs','baselineProbePct'];
  for (const k of ints) if (!Number.isSafeInteger(p[k]) || p[k] <= 0) throw Error('invalid ' + k);
  for (const k of ['maxErrorRate','maxErrorDelta','maxInvalidRate','earlyErrorRate',
    'maxStableErrorRate','minCompleteness']) {
    if (!Number.isFinite(p[k]) || p[k] < 0 || p[k] > 1) throw Error('invalid ' + k);
  }
  if (!Number.isFinite(p.maxLatencyRatio) || p.maxLatencyRatio < 1) throw Error('invalid maxLatencyRatio');
  if (!Array.isArray(p.stages) || !p.stages.length ||
      p.stages.some((n,i) => !Number.isInteger(n) || n < 1 || n > 100 || (i && n <= p.stages[i-1])) ||
      p.stages.at(-1) !== 100) throw Error('stages must increase and end at 100');
  if (p.baselineProbePct > 100 || p.leaseMs <= p.requestTimeoutMs ||
      p.windowMs < p.minStageMs || p.minCompleteness !== 1) throw Error('unsafe timing/completeness policy');
  return p;
}

export function wilson(k, n, z = 1.96) {
  if (!Number.isSafeInteger(n) || !Number.isSafeInteger(k) || n < 1 || k < 0 || k > n) return {low:0,high:1};
  const q = k/n, zz = z*z, den = 1 + zz/n;
  const mid = (q + zz/(2*n))/den;
  const radius = z * Math.sqrt(q*(1-q)/n + zz/(4*n*n))/den;
  return {low: Math.max(0,mid-radius), high:Math.min(1,mid+radius)};
}

function shape(m) {
  const ints = ['started','settled','complete','errors','invalid'];
  if (!m || ints.some(k => !Number.isSafeInteger(m[k]) || m[k] < 0)) return false;
  if (m.settled > m.started || m.complete > m.settled || m.errors > m.settled || m.invalid > m.settled) return false;
  if (m.complete && (!Number.isFinite(m.p95Ms) || m.p95Ms < 0 ||
      !Number.isFinite(m.lastAt))) return false;
  return true;
}

// HOLD keeps the current canary only for evidence collection or confidence uncertainty.
// Every safety hold closes candidate admission; it never silently promotes.
export function decide({state, stable:s, candidate:c, now, p:input}) {
  const p = policy(input);
  const evidence = { stable:s, candidate:c, stage:state.stage, revision:state.revision,
    stageSince:state.stageSince, policy:p, evaluatedAt:now };
  const out = (decision, reason, action='KEEP', extra={}) => ({decision,reason,action,evidence,...extra});
  if (!Number.isFinite(now) || !Number.isFinite(state.stageSince) || state.stageSince > now ||
      !Number.isInteger(state.stage) || state.stage < 0 || state.stage >= p.stages.length)
    return out('HOLD','INVALID_STATE','PAUSE');
  if (['ROLLED_BACK','PAUSED'].includes(state.status)) return out('HOLD','RELEASE_INACTIVE','KEEP');
  if (!shape(s) || !shape(c)) return out('HOLD','METRICS_INVALID','PAUSE');
  // Failures can stop exposure before a full promotion sample is available.
  if (c.invalid > 0 && c.invalid/Math.max(1,c.settled) > p.maxInvalidRate)
    return out('ROLLBACK','CANDIDATE_OUTPUT_INVALID','STOP');
  if (c.errors >= p.maxCandidateFailures) return out('ROLLBACK','CANDIDATE_FAILURE_BUDGET','STOP');
  if (c.settled >= p.earlyMin && c.errors/c.settled > p.earlyErrorRate)
    return out('ROLLBACK','CANDIDATE_ERROR_SPIKE','STOP');
  if (c.complete >= p.earlyMin && c.p95Ms > p.maxP95Ms)
    return out('ROLLBACK','CANDIDATE_LATENCY_SLO','STOP');
  if ((s.settled >= p.earlyMin && s.errors/s.settled > p.maxStableErrorRate) ||
      s.invalid > 0 || (s.complete >= p.earlyMin && s.p95Ms > p.maxStableP95Ms))
    return out('HOLD','STABLE_UNHEALTHY','PAUSE');
  if (s.complete < s.settled || c.complete < c.settled)
    return out('HOLD','METRICS_INCOMPLETE','PAUSE');
  if (s.settled && now-s.lastAt > p.maxMetricAgeMs || c.settled && now-c.lastAt > p.maxMetricAgeMs)
    return out('HOLD','STALE_METRICS','PAUSE');
  if (s.settled < p.minStable || c.settled < p.minCandidate)
    return out('HOLD','INSUFFICIENT_SAMPLES','KEEP');
  if (c.errors/c.settled > p.maxErrorRate || c.errors/c.settled - s.errors/s.settled > p.maxErrorDelta)
    return out('ROLLBACK','CANDIDATE_ERROR_REGRESSION','STOP');
  if (c.p95Ms > s.p95Ms*p.maxLatencyRatio+p.latencySlackMs)
    return out('ROLLBACK','CANDIDATE_LATENCY_REGRESSION','STOP');
  const ci = wilson(c.errors,c.settled), si=wilson(s.errors,s.settled);
  evidence.confidence = {candidateError:ci,stableError:si,z:1.96};
  if (ci.high > p.maxErrorRate || ci.high-si.low > p.maxErrorDelta)
    return out('HOLD','ERROR_CONFIDENCE_INSUFFICIENT','KEEP');
  if (now-state.stageSince < p.minStageMs) return out('HOLD','MINIMUM_DWELL','KEEP');
  if (s.started !== s.settled || c.started !== c.settled) return out('HOLD','IN_FLIGHT_REQUESTS','KEEP');
  const fresh = c.settled-(state.lastCandidateN||0) >= p.freshBatch &&
    s.settled-(state.lastStableN||0) >= p.freshBatch;
  if (!fresh) return out('HOLD','NO_FRESH_BATCH','KEEP');
  const windows = (state.healthyWindows||0)+1;
  if (windows < p.healthyWindows)
    return out('HOLD','CONFIRMATION_WINDOW','CHECKPOINT',{windows});
  if (state.status === 'COMPLETED') return out('HOLD','MONITOR_HEALTHY','CHECKPOINT',{windows:0});
  return out('PROMOTE',state.stage === p.stages.length-1 ? 'RELEASE_VERIFIED':'STAGE_VERIFIED',
    state.stage === p.stages.length-1 ? 'COMPLETE':'ADVANCE',{windows});
}

export function summarize(samples, now) {
  const settled=samples.filter(x=>x.settled);
  const complete=settled.filter(x=>Number.isFinite(x.latencyMs) && x.latencyMs>=0 &&
    typeof x.ok==='boolean' && typeof x.valid==='boolean' && Number.isFinite(x.at));
  const lat=complete.map(x=>x.latencyMs).sort((a,b)=>a-b);
  return {started:samples.length,settled:settled.length,complete:complete.length,
    errors:settled.filter(x=>x.ok===false).length,invalid:settled.filter(x=>x.valid===false && x.ok===true).length,
    p95Ms:lat.length ? lat[Math.max(0,Math.ceil(lat.length*.95)-1)] : null,
    lastAt:complete.length ? Math.max(...complete.map(x=>x.at)) : null};
}
