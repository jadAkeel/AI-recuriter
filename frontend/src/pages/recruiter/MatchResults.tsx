import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { AlertTriangle, FileText, GitCompare, Loader2, Trash2 } from 'lucide-react';
import api from '../../api/client';
import type { DashboardInterviewResult } from '../../types/api';
import { getApiErrorMessage } from '../../utils/errors';

const resultKey = (row: DashboardInterviewResult) =>
  row.session_id || row.report_id || `${row.job_id}-${row.candidate_id}`;

const isMatchOnly = (row: DashboardInterviewResult) => !row.session_id && !row.report_id;

export default function MatchResults() {
  const [results, setResults] = useState<DashboardInterviewResult[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [deletingKey, setDeletingKey] = useState<string | null>(null);

  const loadResults = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const { data } = await api.get<DashboardInterviewResult[]>('/interviews/dashboard-results');
      const rows = Array.isArray(data) ? data : [];
      setResults(rows.filter((row) => row.match_score !== null && row.match_score !== undefined));
    } catch (err: unknown) {
      setError(getApiErrorMessage(err, 'Could not load match results.'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    queueMicrotask(() => void loadResults());
  }, [loadResults]);

  const deleteResult = async (row: DashboardInterviewResult) => {
    const key = resultKey(row);
    const message = row.session_id
      ? 'Delete this interview result and linked match data?'
      : row.report_id
        ? 'Delete this report and linked match result?'
        : 'Delete this saved match result?';
    if (!window.confirm(message)) return;

    setDeletingKey(key);
    setError('');
    try {
      if (row.session_id) {
        await api.delete(`/interviews/${row.session_id}`);
      } else {
        await api.delete('/reports/candidate', {
          params: { job_id: row.job_id, candidate_id: row.candidate_id },
        });
      }
      await loadResults();
    } catch (err: unknown) {
      setError(getApiErrorMessage(err, 'Delete failed. Please try again.'));
    } finally {
      setDeletingKey(null);
    }
  };

  const bestScore = results.reduce((max, row) => Math.max(max, row.match_score ?? 0), 0);

  return (
    <div>
      <div className="flex flex-col gap-1 mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Match Results</h1>
        <p className="text-sm text-gray-500">Saved matches from matching runs, generated reports, and interviews.</p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
        <div className="bg-white rounded-xl border shadow-sm p-4">
          <p className="text-sm text-gray-500">Saved matches</p>
          <p className="text-2xl font-bold text-gray-900 mt-1">{loading ? '...' : results.length}</p>
        </div>
        <div className="bg-white rounded-xl border shadow-sm p-4">
          <p className="text-sm text-gray-500">Best score</p>
          <p className="text-2xl font-bold text-blue-600 mt-1">{loading ? '...' : `${(bestScore * 100).toFixed(1)}%`}</p>
        </div>
        <div className="bg-white rounded-xl border shadow-sm p-4 flex items-center justify-between gap-3">
          <div>
            <p className="text-sm text-gray-500">Run new matching</p>
            <p className="text-sm text-gray-700 mt-1">Create fresh rankings for a job.</p>
          </div>
          <Link to="/matching" className="px-3 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm whitespace-nowrap">
            Open
          </Link>
        </div>
      </div>

      {error && (
        <div className="mb-6 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700 flex items-start gap-3" role="alert">
          <AlertTriangle className="w-5 h-5 mt-0.5 flex-shrink-0" />
          <div>
            <p className="font-medium">Match results could not be loaded.</p>
            <p>{error}</p>
          </div>
        </div>
      )}

      <div className="bg-white rounded-xl border shadow-sm">
        {loading ? (
          <div className="flex items-center justify-center gap-2 py-12 text-sm text-gray-500">
            <Loader2 className="w-4 h-4 animate-spin" />
            Loading match results...
          </div>
        ) : results.length === 0 ? (
          <div className="text-center py-12 px-4">
            <GitCompare className="w-10 h-10 mx-auto text-gray-300 mb-3" />
            <p className="text-gray-500">No saved match results yet.</p>
            <Link to="/matching" className="inline-block mt-3 text-sm text-blue-600 hover:text-blue-700">
              Start matching candidates
            </Link>
          </div>
        ) : (
          <div className="divide-y">
            {results.map((row) => {
              const key = resultKey(row);
              return (
                <div key={key} className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4 p-5">
                  <div>
                    <div className="flex items-center gap-2 flex-wrap">
                      <p className="font-semibold text-gray-900">{row.candidate_name || 'Candidate'}</p>
                      <span className="text-xs text-gray-400">for</span>
                      <p className="text-sm text-gray-600">{row.job_title || 'Job'}</p>
                    </div>
                    <p className="text-sm text-gray-500 mt-1">
                      {row.session_id
                        ? `${row.answered_questions}/${row.total_questions} interview answers submitted`
                        : row.report_id
                          ? 'Generated from candidate report'
                          : 'Saved from matching'}
                    </p>
                  </div>

                  <div className="flex flex-wrap items-center gap-3">
                    <div className="text-right min-w-20">
                      <p className="text-xl font-bold text-blue-600">{((row.match_score ?? 0) * 100).toFixed(1)}%</p>
                      <p className="text-xs text-gray-500">Final match</p>
                    </div>
                    <Link
                      to={`/reports?job_id=${row.job_id}&candidate_id=${row.candidate_id}&auto=1`}
                      className="inline-flex items-center justify-center gap-1 px-3 py-2 border rounded-lg hover:bg-gray-50 text-sm text-gray-700"
                    >
                      <FileText className="w-4 h-4" />
                      {isMatchOnly(row) ? 'Create report' : 'Open report'}
                    </Link>
                    <button
                      onClick={() => deleteResult(row)}
                      disabled={deletingKey === key}
                      className="p-2 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-lg disabled:opacity-50"
                      aria-label="Delete match result"
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
    </div>
  );
}
