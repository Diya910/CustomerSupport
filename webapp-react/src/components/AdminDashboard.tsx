import React, { useEffect, useState, useCallback } from 'react';
import {
  RefreshCw, CheckCircle, XCircle, Clock, ChevronDown, ChevronRight,
  ExternalLink, Zap, AlertCircle, Activity,
} from 'lucide-react';

const LANGSMITH_PROJECT_URL =
  'https://aws.smith.langchain.com/o/70092e4d-eee7-4ed4-b6e7-9ce5d3a51560/projects/p/WorkPodd';

// ── Types ─────────────────────────────────────────────────────────────────────

interface RefundDecision {
  id: number;
  decision: 'approved' | 'denied' | 'pending' | null;
  denial_reason: string | null;
  agent_reasoning: string | null;
  amount_requested: number | null;
  amount_approved: number | null;
  requested_at: string | null;
  decided_at: string | null;
  refund_reason: string | null;
  customer_name: string | null;
  customer_email: string | null;
  account_tier: string | null;
  order_number: string | null;
  product_name: string | null;
  order_amount: number | null;
  order_status: string | null;
}

interface TraceStep {
  name: string;
  run_type: string;
  status: string;
  latency_s: number | null;
  input: string | null;
  output: string | null;
  error: string | null;
}

interface TraceRun {
  id: string;
  name: string;
  run_type: string;
  status: string;
  start_time: string;
  end_time: string;
  latency_s: number | null;
  total_tokens: number | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_cost: string | null;
  error: string | null;
  inputs: string | null;
  outputs: string | null;
  trace_url: string;
  steps: TraceStep[];
}

// ── Small helpers ─────────────────────────────────────────────────────────────

function DecisionBadge({ decision }: { decision: RefundDecision['decision'] }) {
  if (decision === 'approved')
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400">
        <CheckCircle className="w-3 h-3" /> Approved
      </span>
    );
  if (decision === 'denied')
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400">
        <XCircle className="w-3 h-3" /> Denied
      </span>
    );
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400">
      <Clock className="w-3 h-3" /> Pending
    </span>
  );
}

function StatusDot({ status, error }: { status: string; error: string | null }) {
  if (error)
    return <span className="inline-flex items-center gap-1 text-xs text-red-600 dark:text-red-400"><AlertCircle className="w-3 h-3" />error</span>;
  if (status === 'success')
    return <span className="inline-flex items-center gap-1 text-xs text-green-600 dark:text-green-400"><CheckCircle className="w-3 h-3" />success</span>;
  return <span className="inline-flex items-center gap-1 text-xs text-yellow-600 dark:text-yellow-400"><Clock className="w-3 h-3" />{status}</span>;
}

function TierBadge({ tier }: { tier: string | null }) {
  const colours: Record<string, string> = {
    vip: 'bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-400',
    premium: 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400',
    standard: 'bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300',
  };
  const cls = colours[tier?.toLowerCase() ?? ''] ?? 'bg-gray-100 text-gray-700';
  return (
    <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium capitalize ${cls}`}>
      {tier ?? '—'}
    </span>
  );
}

function fmt(iso: string | null): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('en-US', {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

function fmtAmount(n: number | null): string {
  if (n === null || n === undefined) return '—';
  return `$${Number(n).toFixed(2)}`;
}

function Expand({ label, content }: { label: string; content: string | null }) {
  const [open, setOpen] = useState(false);
  if (!content) return <span className="text-gray-400 text-xs">—</span>;
  return (
    <div>
      <button type="button" onClick={() => setOpen(v => !v)}
        className="flex items-center gap-1 text-xs text-blue-600 hover:text-blue-800 dark:text-blue-400 dark:hover:text-blue-300 transition-colors">
        {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        {open ? 'Hide' : label}
      </button>
      {open && (
        <pre className="mt-2 text-xs text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-gray-800 rounded-lg p-3 whitespace-pre-wrap break-words max-w-lg border border-gray-200 dark:border-gray-700">
          {content}
        </pre>
      )}
    </div>
  );
}

function StepTypeBadge({ runType }: { runType: string }) {
  const colours: Record<string, string> = {
    llm: 'bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-400',
    tool: 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-400',
    chain: 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400',
    retriever: 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400',
  };
  const cls = colours[runType] ?? 'bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300';
  return (
    <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${cls}`}>
      {runType}
    </span>
  );
}

function TraceCard({ trace }: { trace: TraceRun }) {
  const [expanded, setExpanded] = useState(false);
  const hasSteps = trace.steps && trace.steps.length > 0;

  return (
    <div className="border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden bg-white dark:bg-gray-800">
      <div
        className={`px-5 py-4 flex items-center justify-between ${hasSteps ? 'cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700/30' : ''} transition-colors`}
        onClick={() => hasSteps && setExpanded(v => !v)}
      >
        <div className="flex items-center gap-4 flex-1 min-w-0">
          {hasSteps && (
            expanded ? <ChevronDown className="w-4 h-4 text-gray-400 flex-shrink-0" /> : <ChevronRight className="w-4 h-4 text-gray-400 flex-shrink-0" />
          )}
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <p className="text-sm font-semibold text-gray-900 dark:text-gray-100 truncate">{trace.name}</p>
              <StepTypeBadge runType={trace.run_type} />
              <StatusDot status={trace.status} error={trace.error} />
            </div>
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
              {fmt(trace.start_time)}
              {trace.latency_s !== null && <span className="ml-3">{trace.latency_s}s</span>}
              {trace.total_tokens && <span className="ml-3">{trace.total_tokens.toLocaleString()} tokens</span>}
              {trace.total_cost && <span className="ml-3">${Number(trace.total_cost).toFixed(4)}</span>}
              {hasSteps && <span className="ml-3 text-blue-500">{trace.steps.length} steps</span>}
            </p>
          </div>
        </div>
        <a href={trace.trace_url} target="_blank" rel="noopener noreferrer"
          onClick={(e) => e.stopPropagation()}
          className="flex items-center gap-1 px-2.5 py-1 text-xs text-blue-600 hover:text-blue-800 dark:text-blue-400 dark:hover:text-blue-300 border border-blue-200 dark:border-blue-800 rounded-lg transition-colors flex-shrink-0 ml-3">
          <ExternalLink className="w-3 h-3" /> LangSmith
        </a>
      </div>

      {/* Input/Output preview */}
      <div className="px-5 pb-3 flex gap-4">
        <Expand label="View input" content={trace.inputs} />
        <Expand label="View output" content={trace.outputs} />
      </div>

      {/* Expanded reasoning steps */}
      {expanded && hasSteps && (
        <div className="border-t border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50 px-5 py-4 space-y-3">
          <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">Reasoning Steps</p>
          <div className="relative pl-4 border-l-2 border-blue-200 dark:border-blue-800 space-y-3">
            {trace.steps.map((step, i) => (
              <div key={i} className="relative">
                <div className="absolute -left-[1.35rem] top-1 w-2.5 h-2.5 rounded-full bg-blue-400 dark:bg-blue-500 border-2 border-white dark:border-gray-900" />
                <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-3">
                  <div className="flex items-center gap-2 mb-1">
                    <p className="text-xs font-medium text-gray-900 dark:text-gray-100">{step.name}</p>
                    <StepTypeBadge runType={step.run_type} />
                    <StatusDot status={step.status} error={step.error} />
                    {step.latency_s !== null && (
                      <span className="text-xs text-gray-400 ml-auto">{step.latency_s}s</span>
                    )}
                  </div>
                  {step.error && (
                    <p className="text-xs text-red-600 dark:text-red-400 mt-1 bg-red-50 dark:bg-red-900/20 rounded px-2 py-1">{step.error}</p>
                  )}
                  <div className="mt-2 space-y-1">
                    <Expand label="Input" content={step.input} />
                    <Expand label="Output" content={step.output} />
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export const AdminDashboard: React.FC = () => {
  const [decisions, setDecisions] = useState<RefundDecision[]>([]);
  const [traces, setTraces] = useState<TraceRun[]>([]);
  const [loadingDecisions, setLoadingDecisions] = useState(false);
  const [loadingTraces, setLoadingTraces] = useState(false);
  const [decisionError, setDecisionError] = useState<string | null>(null);
  const [traceError, setTraceError] = useState<string | null>(null);
  const [lastRefreshed, setLastRefreshed] = useState<Date | null>(null);
  const [filterDecision, setFilterDecision] = useState<'all' | 'approved' | 'denied' | 'pending'>('all');

  const basePath = import.meta.env.BASE_URL.replace(/\/$/, '');

  const fetchDecisions = useCallback(async (showLoading: boolean) => {
    if (showLoading) setLoadingDecisions(true);
    setDecisionError(null);
    try {
      const res = await fetch(`${basePath}/workflows/refunds/decisions?limit=200`);
      if (!res.ok) throw new Error(`Server returned ${res.status}`);
      const data = await res.json();
      setDecisions(data.decisions ?? []);
    } catch (e) {
      setDecisionError(e instanceof Error ? e.message : 'Failed to load decisions');
    } finally {
      setLoadingDecisions(false);
    }
  }, [basePath]);

  const fetchTraces = useCallback(async (showLoading: boolean) => {
    if (showLoading) setLoadingTraces(true);
    setTraceError(null);
    try {
      const res = await fetch(`${basePath}/workflows/traces?limit=20`);
      if (!res.ok) throw new Error(`Server returned ${res.status}`);
      const data = await res.json();
      setTraces(data.traces ?? []);
    } catch (e) {
      setTraceError(e instanceof Error ? e.message : 'Failed to load traces');
    } finally {
      setLoadingTraces(false);
    }
  }, [basePath]);

  const refreshAll = useCallback((showLoading = false) => {
    fetchDecisions(showLoading);
    fetchTraces(showLoading);
    setLastRefreshed(new Date());
  }, [fetchDecisions, fetchTraces]);

  useEffect(() => {
    refreshAll(true);
    const interval = setInterval(() => refreshAll(false), 10000);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const filtered = filterDecision === 'all'
    ? decisions
    : decisions.filter(d => d.decision === filterDecision);

  const counts = {
    total: decisions.length,
    approved: decisions.filter(d => d.decision === 'approved').length,
    denied: decisions.filter(d => d.decision === 'denied').length,
    pending: decisions.filter(d => !d.decision || d.decision === 'pending').length,
  };

  return (
    <div className="flex-1 overflow-y-auto bg-gray-50 dark:bg-gray-900">
      <div className="max-w-7xl mx-auto p-6 space-y-8">

        {/* ── Header ── */}
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-xl font-bold text-gray-900 dark:text-gray-100">Admin Dashboard</h2>
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
              Refund decisions audit log + live agent reasoning traces via LangSmith
            </p>
          </div>
          <div className="flex items-center gap-3">
            {lastRefreshed && (
              <span className="text-xs text-gray-400">Updated {lastRefreshed.toLocaleTimeString()}</span>
            )}
            <a href={LANGSMITH_PROJECT_URL} target="_blank" rel="noopener noreferrer"
              className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-medium transition-colors">
              <ExternalLink className="w-4 h-4" /> Open in LangSmith
            </a>
            <button type="button" onClick={() => refreshAll(true)}
              disabled={loadingDecisions || loadingTraces}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-50 transition-colors disabled:opacity-50">
              <RefreshCw className={`w-4 h-4 ${loadingDecisions || loadingTraces ? 'animate-spin' : ''}`} />
              Refresh
            </button>
          </div>
        </div>

        {/* ── Stats ── */}
        <div className="grid grid-cols-4 gap-4">
          {[
            { label: 'Total Decisions', value: counts.total },
            { label: 'Approved', value: counts.approved },
            { label: 'Denied', value: counts.denied },
            { label: 'Pending', value: counts.pending },
          ].map(s => (
            <div key={s.label} className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
              <p className="text-sm text-gray-500 dark:text-gray-400">{s.label}</p>
              <p className="text-2xl font-bold text-gray-900 dark:text-gray-100 mt-1">{s.value}</p>
            </div>
          ))}
        </div>

        {/* ── SECTION 1: Live Reasoning Traces ── */}
        <section>
          <div className="flex items-center gap-2 mb-4">
            <Activity className="w-5 h-5 text-blue-600" />
            <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100">Live Reasoning Traces</h3>
            <span className="text-xs text-gray-400">(powered by LangSmith — auto-refreshes every 10s)</span>
          </div>

          {traceError && (
            <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-700 rounded-xl p-4 text-sm text-red-800 dark:text-red-300 mb-4">
              {traceError}
            </div>
          )}

          {loadingTraces && traces.length === 0 ? (
            <div className="flex items-center justify-center py-12 text-gray-400 bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700">
              <RefreshCw className="w-5 h-5 animate-spin mr-2" /> Loading traces from LangSmith...
            </div>
          ) : traces.length === 0 ? (
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-10 text-center">
              <Zap className="w-8 h-8 text-gray-300 dark:text-gray-600 mx-auto mb-2" />
              <p className="text-gray-400 dark:text-gray-500 text-sm">No traces yet.</p>
              <p className="text-gray-400 dark:text-gray-500 text-xs mt-1">Process a refund in the Chat tab and traces will appear here.</p>
            </div>
          ) : (
            <div className="space-y-3">
              {traces.map(t => <TraceCard key={t.id} trace={t} />)}
            </div>
          )}
        </section>

        {/* ── SECTION 2: Refund Decisions Audit Log ── */}
        <section>
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <CheckCircle className="w-5 h-5 text-green-600" />
              <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100">Refund Decisions Audit Log</h3>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-sm text-gray-500 dark:text-gray-400">Filter:</span>
              {(['all', 'approved', 'denied', 'pending'] as const).map(f => (
                <button key={f} type="button" onClick={() => setFilterDecision(f)}
                  className={`px-3 py-1 rounded-full text-xs font-medium capitalize transition-colors ${
                    filterDecision === f
                      ? 'bg-blue-600 text-white'
                      : 'bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700'
                  }`}>
                  {f === 'all' ? `All (${counts.total})` : f}
                </button>
              ))}
            </div>
          </div>

          {decisionError && (
            <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-700 rounded-xl p-4 text-sm text-red-800 dark:text-red-300 mb-4">
              {decisionError}
            </div>
          )}

          {loadingDecisions && decisions.length === 0 ? (
            <div className="flex items-center justify-center py-12 text-gray-400 bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700">
              <RefreshCw className="w-5 h-5 animate-spin mr-2" /> Loading decisions...
            </div>
          ) : filtered.length === 0 ? (
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-10 text-center">
              <p className="text-gray-400 dark:text-gray-500 text-sm">No refund decisions yet.</p>
              <p className="text-gray-400 dark:text-gray-500 text-xs mt-1">Process a refund in the Chat tab to see decisions here.</p>
            </div>
          ) : (
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900">
                      <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">Decision</th>
                      <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">Customer</th>
                      <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">Order</th>
                      <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">Amount</th>
                      <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">Reason / Denial</th>
                      <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">Agent Reasoning</th>
                      <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">Requested</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
                    {filtered.map(d => (
                      <tr key={d.id} className="hover:bg-gray-50 dark:hover:bg-gray-700/30 transition-colors">
                        <td className="px-4 py-3"><DecisionBadge decision={d.decision} /></td>
                        <td className="px-4 py-3">
                          <p className="font-medium text-gray-900 dark:text-gray-100 text-xs">{d.customer_name ?? '—'}</p>
                          <p className="text-gray-500 dark:text-gray-400 text-xs">{d.customer_email ?? '—'}</p>
                          <div className="mt-1"><TierBadge tier={d.account_tier} /></div>
                        </td>
                        <td className="px-4 py-3">
                          <p className="font-mono text-xs text-gray-700 dark:text-gray-300">{d.order_number ?? '—'}</p>
                          <p className="text-gray-500 dark:text-gray-400 text-xs mt-0.5 max-w-[160px] truncate" title={d.product_name ?? ''}>
                            {d.product_name ?? '—'}
                          </p>
                        </td>
                        <td className="px-4 py-3">
                          <p className="text-xs font-medium">
                            {d.decision === 'approved'
                              ? <span className="text-green-700 dark:text-green-400">{fmtAmount(d.amount_approved)}</span>
                              : <span className="text-gray-400">{fmtAmount(d.amount_requested)}</span>}
                          </p>
                          <p className="text-xs text-gray-400 mt-0.5">req: {fmtAmount(d.amount_requested)}</p>
                        </td>
                        <td className="px-4 py-3 max-w-[180px]">
                          <p className="text-xs text-gray-700 dark:text-gray-300 line-clamp-2" title={d.refund_reason ?? ''}>
                            {d.refund_reason ?? '—'}
                          </p>
                          {d.denial_reason && (
                            <p className="text-xs text-red-600 dark:text-red-400 mt-1 line-clamp-2" title={d.denial_reason}>
                              {d.denial_reason}
                            </p>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          <Expand label="View reasoning" content={d.agent_reasoning} />
                        </td>
                        <td className="px-4 py-3 whitespace-nowrap">
                          <p className="text-xs text-gray-500 dark:text-gray-400">{fmt(d.requested_at)}</p>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </section>

      </div>
    </div>
  );
};
