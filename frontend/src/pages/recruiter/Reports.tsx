import { useState, useEffect } from 'react';
import api from '../../api/client';
import { BarChart3, Loader2 } from 'lucide-react';
import type { ReportResponse } from '../../types/api';

export default function Reports() {
  const [jobId, setJobId] = useState('');
  const [candidateId, setCandidateId] = useState('');
  const [report, setReport] = useState<ReportResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [jobs, setJobs] = useState<{ job_id: string; title: string }[]>([]);
  const [candidates, setCandidates] = useState<{ candidate_id: string; full_name: string | null }[]>([]);

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

  const generateReport = async () => {
    setLoading(true);
    try {
      const { data } = await api.post<ReportResponse>('/reports/candidate', { job_id: jobId, candidate_id: candidateId });
      setReport(data);
    } catch { setReport(null); }
    setLoading(false);
  };

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Reports</h1>

      <div className="bg-white rounded-xl shadow-sm border p-6 mb-6">
        <div className="grid grid-cols-2 gap-3 mb-3">
          <select value={jobId} onChange={(e) => setJobId(e.target.value)}
            className="px-3 py-2 border rounded-lg outline-none focus:ring-2 focus:ring-blue-500 bg-white">
            <option value="">-- Select Job --</option>
            {jobs.map(j => <option key={j.job_id} value={j.job_id}>{j.title}</option>)}
          </select>
          <select value={candidateId} onChange={(e) => setCandidateId(e.target.value)}
            className="px-3 py-2 border rounded-lg outline-none focus:ring-2 focus:ring-blue-500 bg-white">
            <option value="">-- Select Candidate --</option>
            {candidates.map(c => <option key={c.candidate_id} value={c.candidate_id}>{c.full_name || c.candidate_id}</option>)}
          </select>
        </div>
        <button onClick={generateReport} disabled={loading || !jobId || !candidateId}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50">
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <BarChart3 className="w-4 h-4" />}
          {loading ? 'Generating...' : 'Generate Report'}
        </button>
      </div>

      {report && (
        <div className="bg-white rounded-xl shadow-sm border p-6">
          <div className="flex items-center justify-between mb-6">
            <div>
              <h2 className="text-xl font-bold text-gray-900">{report.candidate_name}</h2>
              <p className="text-gray-500">{report.job_title}</p>
            </div>
            <div className="text-right">
              <p className="text-3xl font-bold text-blue-600">{(report.score_breakdown.overall_score * 100).toFixed(1)}%</p>
              <p className="text-sm text-gray-500">Overall Match</p>
            </div>
          </div>

          <div className="grid grid-cols-3 gap-4 mb-6">
            <div className="bg-blue-50 rounded-lg p-4 text-center">
              <p className="text-lg font-bold text-blue-700">{(report.score_breakdown.similarity_score * 100).toFixed(0)}%</p>
              <p className="text-xs text-blue-600">Similarity</p>
            </div>
            <div className="bg-green-50 rounded-lg p-4 text-center">
              <p className="text-lg font-bold text-green-700">{(report.score_breakdown.required_skills_score * 100).toFixed(0)}%</p>
              <p className="text-xs text-green-600">Required Skills</p>
            </div>
            <div className="bg-purple-50 rounded-lg p-4 text-center">
              <p className="text-lg font-bold text-purple-700">{(report.score_breakdown.optional_skills_score * 100).toFixed(0)}%</p>
              <p className="text-xs text-purple-600">Optional Skills</p>
            </div>
          </div>

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

          <div className="grid grid-cols-2 gap-4 mb-4">
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
