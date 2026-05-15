import { useState, useEffect } from 'react';
import api from '../../api/client';
import { BarChart3 } from 'lucide-react';
import type { Job, ReportResponse } from '../../types/api';

export default function CandidateResults() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selectedJobId, setSelectedJobId] = useState('');
  const [report, setReport] = useState<ReportResponse | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    api.get<Job[]>('/jobs').then(({ data }) => setJobs(Array.isArray(data) ? data : [])).catch(() => {
      // Keep the selector empty if jobs cannot be loaded.
    });
  }, []);

  const loadReport = async () => {
    if (!selectedJobId) return;
    setLoading(true);
    try {
      const me = (await api.get<{ candidate_id: string }>('/candidates/me')).data;
      const { data } = await api.post('/reports/candidate', { job_id: selectedJobId, candidate_id: me.candidate_id });
      setReport(data);
    } catch {
      // Leave the current state unchanged on report failures.
    }
    setLoading(false);
  };

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-6">My Results</h1>

      {!report && (
        <div className="bg-white rounded-xl shadow-sm border p-6">
          <p className="text-gray-600 mb-4">Select a job to view your evaluation report.</p>
          <div className="flex gap-3">
            <select value={selectedJobId} onChange={(e) => setSelectedJobId(e.target.value)}
              className="flex-1 px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 outline-none bg-white">
              <option value="">-- Select a Job --</option>
              {jobs.map((job) => (
                <option key={job.job_id} value={job.job_id}>
                  {job.title || 'Untitled'} ({job.seniority || 'any'})
                </option>
              ))}
            </select>
            <button onClick={loadReport} disabled={!selectedJobId || loading}
              className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50">
              <BarChart3 className="w-4 h-4" /> {loading ? 'Loading...' : 'View Report'}
            </button>
          </div>
        </div>
      )}

      {report && (
        <div className="space-y-4">
          <div className="bg-white rounded-xl shadow-sm border p-6">
            <div className="text-center mb-6">
              <p className="text-5xl font-bold text-blue-600 mb-2">
                {(report.score_breakdown.overall_score * 100).toFixed(1)}%
              </p>
              <p className="text-gray-500">Overall Match for {report.job_title}</p>
            </div>

            <div className="grid grid-cols-3 gap-4 mb-6">
              <div className="bg-blue-50 rounded-lg p-3 text-center">
                <p className="text-lg font-bold text-blue-700">{(report.score_breakdown.similarity_score * 100).toFixed(0)}%</p>
                <p className="text-xs text-blue-600">Similarity</p>
              </div>
              <div className="bg-green-50 rounded-lg p-3 text-center">
                <p className="text-lg font-bold text-green-700">{(report.score_breakdown.required_skills_score * 100).toFixed(0)}%</p>
                <p className="text-xs text-green-600">Required Skills</p>
              </div>
              <div className="bg-purple-50 rounded-lg p-3 text-center">
                <p className="text-lg font-bold text-purple-700">{(report.score_breakdown.optional_skills_score * 100).toFixed(0)}%</p>
                <p className="text-xs text-purple-600">Optional Skills</p>
              </div>
            </div>

            <div className="bg-gray-50 rounded-lg p-4 mb-6">
              <p className="text-sm text-gray-700"><span className="font-medium">Recommendation:</span> {report.recommendation}</p>
            </div>

            <button onClick={() => setReport(null)}
              className="px-4 py-2 border rounded-lg hover:bg-gray-50 text-sm">Back to Jobs</button>
          </div>

          <div className="bg-white rounded-xl shadow-sm border p-6">
            <h3 className="font-semibold text-gray-900 mb-4">Skill Breakdown</h3>
            <div className="space-y-3">
              {report.skill_scores && Object.entries(report.skill_scores).map(([skill, score]) => (
                <div key={skill}>
                  <div className="flex justify-between text-sm mb-1">
                    <span>{skill}</span>
                    <span className="text-gray-500">{(score * 100).toFixed(0)}%</span>
                  </div>
                  <div className="w-full bg-gray-100 rounded-full h-2">
                    <div className="bg-blue-600 h-2 rounded-full" style={{ width: `${score * 100}%` }} />
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
