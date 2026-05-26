import { useCallback, useState, useEffect, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import api from '../../api/client';
import { AlertTriangle, BarChart3, FileText, Loader2, Trash2 } from 'lucide-react';
import type { DashboardInterviewResult, ReportResponse } from '../../types/api';
import { getApiErrorMessage } from '../../utils/errors';

const formatPct = (value?: number | null) => `${Math.max(0, Math.min(100, (value ?? 0) * 100)).toFixed(1)}%`;

const factorLabel = (key: string) => {
  const labels: Record<string, string> = {
    skill_required: 'Required skills',
    skill_optional: 'Optional skills',
    semantic: 'Similarity',
    experience: 'Experience',
    seniority_match: 'Seniority',
    cross_encoder: 'LLM rerank',
    cross_encoder_adjustment: 'LLM rerank adjustment',
    base_hybrid: 'Base match',
  };
  return labels[key] || key.replace(/_/g, ' ');
};

export default function Reports() {
  const [searchParams] = useSearchParams();
  const [jobId, setJobId] = useState('');
  const [candidateId, setCandidateId] = useState('');
  const [report, setReport] = useState<ReportResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [jobs, setJobs] = useState<{ job_id: string; title: string }[]>([]);
  const [candidates, setCandidates] = useState<{ candidate_id: string; full_name: string | null }[]>([]);
  const [savedReports, setSavedReports] = useState<DashboardInterviewResult[]>([]);
  const [savedReportsLoading, setSavedReportsLoading] = useState(true);
  const [savedReportsError, setSavedReportsError] = useState('');
  const [deletingKey, setDeletingKey] = useState<string | null>(null);
  const autoLoadedRef = useRef(false);

  useEffect(() => {
    const queryJobId = searchParams.get('job_id') || '';
    const queryCandidateId = searchParams.get('candidate_id') || '';
    queueMicrotask(() => {
      if (queryJobId) setJobId(queryJobId);
      if (queryCandidateId) setCandidateId(queryCandidateId);
    });
  }, [searchParams]);

  useEffect(() => {
    const fetchOptions = async () => {
      try {
        const [jobsRes, candsRes] = await Promise.all([
          api.get('/jobs'),
          api.get('/candidates'),
        ]);
        setJobs(Array.isArray(jobsRes.data) ? jobsRes.data : []);
        setCandidates(Array.isArray(candsRes.data) ? candsRes.data : []);
      } catch { /* ignore */ }
    };
    fetchOptions();
  }, []);

  const loadSavedReports = useCallback(async () => {
    setSavedReportsLoading(true);
    setSavedReportsError('');
    try {
      const { data } = await api.get<DashboardInterviewResult[]>('/interviews/dashboard-results');
      const rows = Array.isArray(data) ? data : [];
      setSavedReports(rows.filter((row) => Boolean(row.report_id)));
    } catch (err: unknown) {
      setSavedReportsError(getApiErrorMessage(err, 'Could not load saved reports.'));
    } finally {
      setSavedReportsLoading(false);
    }
  }, []);

  useEffect(() => {
    queueMicrotask(() => void loadSavedReports());
  }, [loadSavedReports]);

  const generateReport = useCallback(async (selectedJobId = jobId, selectedCandidateId = candidateId) => {
    if (!selectedJobId || !selectedCandidateId) return;
    setLoading(true);
    setError('');
    try {
      const { data } = await api.post<ReportResponse>('/reports/candidate', { job_id: selectedJobId, candidate_id: selectedCandidateId });
      setReport(data);
      await loadSavedReports();
    } catch (err: unknown) {
      setReport(null);
      setError(getApiErrorMessage(err, 'Could not generate the report. Please try again.'));
    }
    setLoading(false);
  }, [candidateId, jobId, loadSavedReports]);

  useEffect(() => {
    if (searchParams.get('auto') !== '1' || !jobId || !candidateId || autoLoadedRef.current) return;
    autoLoadedRef.current = true;
    queueMicrotask(() => void generateReport(jobId, candidateId));
  }, [candidateId, generateReport, jobId, searchParams]);

  const openSavedReport = async (row: DashboardInterviewResult) => {
    setJobId(row.job_id);
    setCandidateId(row.candidate_id);
    await generateReport(row.job_id, row.candidate_id);
  };

  const deleteSavedReport = async (row: DashboardInterviewResult) => {
    const key = row.report_id || `${row.job_id}-${row.candidate_id}`;
    if (!window.confirm('Delete this report and linked match result?')) return;
    setDeletingKey(key);
    setSavedReportsError('');
    try {
      await api.delete('/reports/candidate', {
        params: { job_id: row.job_id, candidate_id: row.candidate_id },
      });
      if (jobId === row.job_id && candidateId === row.candidate_id) {
        setReport(null);
      }
      await loadSavedReports();
    } catch (err: unknown) {
      setSavedReportsError(getApiErrorMessage(err, 'Delete failed. Please try again.'));
    } finally {
      setDeletingKey(null);
    }
  };

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Reports</h1>
        <p className="text-sm text-gray-500 mt-1">Open saved reports or generate a new candidate report.</p>
      </div>

      <div className="bg-white rounded-xl shadow-sm border mb-6">
        <div className="p-5 border-b flex items-center justify-between gap-3">
          <div>
            <h2 className="font-semibold text-gray-900">Saved Reports</h2>
            <p className="text-sm text-gray-500">Previously generated reports stay available here.</p>
          </div>
          <div className="text-sm text-gray-500">
            {savedReportsLoading ? '...' : `${savedReports.length} saved`}
          </div>
        </div>

        {savedReportsError && (
          <div className="m-5 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700 flex items-start gap-3" role="alert">
            <AlertTriangle className="w-5 h-5 mt-0.5 flex-shrink-0" />
            <div>
              <p className="font-medium">Saved reports could not be loaded.</p>
              <p>{savedReportsError}</p>
            </div>
          </div>
        )}

        {savedReportsLoading ? (
          <div className="flex items-center justify-center gap-2 py-10 text-sm text-gray-500">
            <Loader2 className="w-4 h-4 animate-spin" />
            Loading saved reports...
          </div>
        ) : savedReports.length === 0 ? (
          <div className="text-center py-10 px-4">
            <FileText className="w-10 h-10 mx-auto text-gray-300 mb-3" />
            <p className="text-gray-500">No reports have been generated yet.</p>
          </div>
        ) : (
          <div className="divide-y">
            {savedReports.map((row) => {
              const key = row.report_id || `${row.job_id}-${row.candidate_id}`;
              return (
                <div key={key} className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-3 p-5">
                  <div>
                    <div className="flex items-center gap-2 flex-wrap">
                      <p className="font-semibold text-gray-900">{row.candidate_name || 'Candidate'}</p>
                      <span className="text-xs text-gray-400">for</span>
                      <p className="text-sm text-gray-600">{row.job_title || 'Job'}</p>
                    </div>
                    <p className="text-sm text-gray-500 mt-1">
                      {row.session_id ? 'Built with interview analysis' : 'Generated from candidate profile'}
                    </p>
                  </div>
                  <div className="flex flex-wrap items-center gap-3">
                    <div className="text-right min-w-20">
                      <p className="text-xl font-bold text-blue-600">{((row.report_score ?? row.match_score ?? 0) * 100).toFixed(1)}%</p>
                      <p className="text-xs text-gray-500">Report score</p>
                    </div>
                    <button
                      onClick={() => openSavedReport(row)}
                      className="inline-flex items-center justify-center gap-1 px-3 py-2 border rounded-lg hover:bg-gray-50 text-sm text-gray-700"
                    >
                      <FileText className="w-4 h-4" />
                      Open
                    </button>
                    <button
                      onClick={() => deleteSavedReport(row)}
                      disabled={deletingKey === key}
                      className="p-2 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-lg disabled:opacity-50"
                      aria-label="Delete report"
                    >
                      {deletingKey === key ? <Loader2 className="w-4 h-4 animate-spin" /> : <Trash2 className="w-4 h-4" />}
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div className="bg-white rounded-xl shadow-sm border p-6 mb-6">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-3">
          <select value={jobId} onChange={(e) => { setJobId(e.target.value); setReport(null); setError(''); }}
            className="px-3 py-2 border rounded-lg outline-none focus:ring-2 focus:ring-blue-500 bg-white">
            <option value="">-- Select Job --</option>
            {jobs.map(j => <option key={j.job_id} value={j.job_id}>{j.title}</option>)}
          </select>
          <select value={candidateId} onChange={(e) => { setCandidateId(e.target.value); setReport(null); setError(''); }}
            className="px-3 py-2 border rounded-lg outline-none focus:ring-2 focus:ring-blue-500 bg-white">
            <option value="">-- Select Candidate --</option>
            {candidates.map(c => <option key={c.candidate_id} value={c.candidate_id}>{c.full_name || c.candidate_id}</option>)}
          </select>
        </div>
        <button onClick={() => generateReport()} disabled={loading || !jobId || !candidateId}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50">
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <BarChart3 className="w-4 h-4" />}
          {loading ? 'Generating...' : 'Generate Candidate Report'}
        </button>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 mb-6 flex items-start gap-3" role="alert">
          <AlertTriangle className="w-5 h-5 text-red-500 mt-0.5 flex-shrink-0" />
          <div>
            <p className="text-sm font-medium text-red-800">Report could not be loaded</p>
            <p className="text-sm text-red-600 mt-1">{error}</p>
            <button onClick={() => generateReport()} disabled={loading || !jobId || !candidateId}
              className="mt-3 px-3 py-1.5 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 text-sm">
              Try again
            </button>
          </div>
        </div>
      )}

      {report && (
        <div className="bg-white rounded-xl shadow-sm border p-6">
          <div className="flex items-center justify-between mb-6">
            <div>
              <h2 className="text-xl font-bold text-gray-900">{report.candidate_name}</h2>
              <p className="text-gray-500">{report.job_title}</p>
            </div>
            <div className="flex items-center gap-4">
              <div className="text-right">
                <p className="text-3xl font-bold text-blue-600">{formatPct(report.score_breakdown.overall_score)}</p>
                <p className="text-sm text-gray-500">Overall Match</p>
              </div>
              <button
                onClick={async () => {
                  if (!window.confirm('Delete this report?')) return;
                  try {
                    await api.delete(`/reports/candidate?job_id=${jobId}&candidate_id=${candidateId}`);
                    setReport(null);
                    await loadSavedReports();
                  } catch {
                    alert('Failed to delete report');
                  }
                }}
                className="p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded transition-colors"
                title="Delete report"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
            <div className="bg-blue-50 rounded-lg p-4 text-center">
              <p className="text-lg font-bold text-blue-700">{formatPct(report.score_breakdown.similarity_score)}</p>
              <p className="text-xs text-blue-600">Similarity</p>
            </div>
            <div className="bg-green-50 rounded-lg p-4 text-center">
              <p className="text-lg font-bold text-green-700">{formatPct(report.score_breakdown.required_skills_score)}</p>
              <p className="text-xs text-green-600">Required Skills</p>
            </div>
            <div className="bg-purple-50 rounded-lg p-4 text-center">
              <p className="text-lg font-bold text-purple-700">{formatPct(report.score_breakdown.optional_skills_score)}</p>
              <p className="text-xs text-purple-600">Optional Skills</p>
            </div>
          </div>

          {report.score_breakdown.scoring_formula && (
            <div className="bg-indigo-50 border border-indigo-100 rounded-lg p-4 mb-6">
              <div className="flex items-start justify-between gap-3 mb-2">
                <div>
                  <h3 className="font-semibold text-indigo-800 text-sm">Score Calculation</h3>
                  <p className="text-xs text-indigo-600 mt-0.5">Model: {report.score_breakdown.scoring_model || 'match scoring'}</p>
                </div>
                <span className="text-sm font-bold text-indigo-700">{formatPct(report.score_breakdown.overall_score)}</span>
              </div>
              <p className="text-xs text-gray-700 bg-white/80 rounded-md border border-white p-2 mb-3">{report.score_breakdown.scoring_formula}</p>
              {Object.keys(report.score_breakdown.score_contributions || {}).length > 0 && (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs">
                  {Object.entries(report.score_breakdown.score_contributions || {}).map(([key, contribution]) => (
                    <div key={key} className="bg-white rounded-md border border-indigo-100 p-2 flex items-center justify-between gap-2">
                      <span className="text-gray-600">{factorLabel(key)}</span>
                      <span className="font-semibold text-indigo-700">
                        +{(contribution * 100).toFixed(1)} pts
                        {report.score_breakdown.score_weights?.[key] !== undefined && ` (${formatPct(report.score_breakdown.score_weights[key])} weight)`}
                      </span>
                    </div>
                  ))}
                </div>
              )}
              {Object.keys(report.score_breakdown.score_penalties || {}).length > 0 && (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs mt-2">
                  {Object.entries(report.score_breakdown.score_penalties || {}).map(([key, penalty]) => (
                    <div key={key} className="bg-red-50 rounded-md border border-red-100 p-2 flex items-center justify-between gap-2">
                      <span className="text-red-600">{factorLabel(key)}</span>
                      <span className="font-semibold text-red-700">-{(penalty * 100).toFixed(1)} pts</span>
                    </div>
                  ))}
                </div>
              )}
              {(report.score_breakdown.pre_cap_score !== null && report.score_breakdown.pre_cap_score !== undefined) && (
                <p className="text-xs text-gray-500 mt-3">
                  Before cap: {formatPct(report.score_breakdown.pre_cap_score)}
                  {report.score_breakdown.score_cap !== null && report.score_breakdown.score_cap !== undefined && `, required-skill cap: ${formatPct(report.score_breakdown.score_cap)}`}
                </p>
              )}
              {report.score_breakdown.score_cap_reason && (
                <p className="text-xs text-gray-500 mt-1">{report.score_breakdown.score_cap_reason}</p>
              )}
            </div>
          )}

          <div className="mb-6">
            <h3 className="font-semibold mb-3">Skill Gap Analysis</h3>
            <div className="space-y-2">
              {report.skill_gap?.items.map((item) => (
                <div key={item.skill} className="flex items-center gap-3">
                  <div className={`w-2 h-2 rounded-full ${item.matched ? 'bg-green-500' : 'bg-red-500'}`} />
                  <span className="text-sm">{item.skill}</span>
                  <span className="text-xs text-gray-400">{item.required ? '(required)' : '(optional)'}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4">
            <div>
              <h4 className="font-medium text-green-700 mb-2">Strengths</h4>
              <div className="flex gap-2 flex-wrap">
                {report.strengths.map((s: string) => <span key={s} className="px-2 py-0.5 bg-green-50 text-green-700 rounded text-xs">{s}</span>)}
              </div>
            </div>
            <div>
              <h4 className="font-medium text-red-700 mb-2">Weaknesses</h4>
              <div className="flex gap-2 flex-wrap">
                {report.weaknesses.map((s: string) => <span key={s} className="px-2 py-0.5 bg-red-50 text-red-700 rounded text-xs">{s}</span>)}
              </div>
            </div>
          </div>

          <div className="bg-gray-50 rounded-lg p-4">
            <p className="text-sm text-gray-700"><span className="font-medium">Recommendation:</span> {report.recommendation}</p>
          </div>
        </div>
      )}
    </div>
  );
}
