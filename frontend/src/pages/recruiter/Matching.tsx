import { useState, useEffect, useRef } from 'react';
import api from '../../api/client';
import { GitCompare, Search, AlertTriangle, Star, X, ChevronDown, ChevronUp, CheckCircle2, XCircle, TrendingUp, BarChart3, Brain, Download, Loader2, Filter } from 'lucide-react';
import type { ApiParams, Candidate, Job, MatchResult, SkillCategory } from '../../types/api';
import { getApiErrorMessage } from '../../utils/errors';

export default function Matching() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [candidates, setCandidates] = useState<Record<string, Candidate>>({});
  const [selectedJobId, setSelectedJobId] = useState('');
  const [results, setResults] = useState<MatchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [minScore, setMinScore] = useState(0);
  const [showOverqualified, setShowOverqualified] = useState(false);
  const [previewCandidate, setPreviewCandidate] = useState<(Candidate & { match?: MatchResult }) | null>(null);
  const [expandedAnalysis, setExpandedAnalysis] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const perPage = 5;

  // ── Filters (same as Candidates page) ──
  const [search, setSearch] = useState('');
  const [selectedSkills, setSelectedSkills] = useState<string[]>([]);
  const [skillCategories, setSkillCategories] = useState<SkillCategory>({});
  const [showSkillPicker, setShowSkillPicker] = useState(false);
  const [minYears, setMinYears] = useState<number | ''>('');
  const [maxYears, setMaxYears] = useState<number | ''>('');
  const [skillLogic, setSkillLogic] = useState<'and' | 'or'>('and');
  const [enableCrossEncoder, setEnableCrossEncoder] = useState(false);
  const [educationSearch, setEducationSearch] = useState('');
  const [university, setUniversity] = useState('');
  const [degree, setDegree] = useState('');
  const [showAdvancedFilters, setShowAdvancedFilters] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const skillPickerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    Promise.all([
      api.get<Job[]>('/jobs'),
      api.get<Candidate[]>('/candidates'),
      api.get<SkillCategory>('/skills/categories'),
    ]).then(([jobsRes, candRes, catRes]) => {
      setJobs(Array.isArray(jobsRes.data) ? jobsRes.data : []);
      const map: Record<string, Candidate> = {};
      (Array.isArray(candRes.data) ? candRes.data : []).forEach((c) => {
        map[c.candidate_id] = c;
      });
      setCandidates(map);
      setSkillCategories(catRes.data || {});
    });
  }, []);

  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (skillPickerRef.current && !skillPickerRef.current.contains(e.target as Node)) {
        setShowSkillPicker(false);
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  const hasFilters = search || selectedSkills.length > 0 || minYears !== '' || maxYears !== '' || educationSearch || university || degree;

  const clearFilters = () => {
    setSearch('');
    setSelectedSkills([]);
    setSkillLogic('and');
    setMinYears('');
    setMaxYears('');
    setEducationSearch('');
    setUniversity('');
    setDegree('');
    setEnableCrossEncoder(false);
  };

  const toggleSkill = (skill: string) => {
    setSelectedSkills((prev) =>
      prev.includes(skill) ? prev.filter((s) => s !== skill) : [...prev, skill]
    );
  };

  const handleMatch = async () => {
    if (!selectedJobId) return;
    setLoading(true);
    setPage(1);
    setError(null);
    try {
      const params: ApiParams = { cross_encoder_top_k: enableCrossEncoder ? 5 : 0 };
      if (search) params.search = search;
      if (selectedSkills.length > 0) { params.skills = selectedSkills.join(','); params.skill_logic = skillLogic; }
      if (minYears !== '') params.min_years = Number(minYears);
      if (maxYears !== '') params.max_years = Number(maxYears);
      if (educationSearch) params.education_search = educationSearch;
      if (university) params.university = university;
      if (degree) params.degree = degree;
      const { data } = await api.post<{ results?: MatchResult[] }>(`/jobs/${selectedJobId}/match`, null, { params });
      setResults((data.results || []).sort((a, b) => b.score - a.score));
    } catch (err: unknown) {
      setError(getApiErrorMessage(err, 'Matching request failed'));
      setResults([]);
    }
    setLoading(false);
  };

  const selectedJob = jobs.find((j) => j.job_id === selectedJobId);

  const filteredResults = results.filter((r) => {
    if (r.score < minScore) return false;
    if (!showOverqualified && r.reasoning?.overqualified) return false;
    return true;
  });

  const paginatedResults = filteredResults.slice(0, page * perPage);

  const scoreColor = (score: number) => {
    if (score >= 0.7) return 'text-green-600';
    if (score >= 0.4) return 'text-yellow-600';
    return 'text-red-600';
  };

  const scoreBg = (score: number) => {
    if (score >= 0.7) return 'bg-green-500';
    if (score >= 0.4) return 'bg-yellow-500';
    return 'bg-red-500';
  };

  const scoreRing = (score: number) => {
    if (score >= 0.7) return 'stroke-green-500';
    if (score >= 0.4) return 'stroke-yellow-500';
    return 'stroke-red-500';
  };

  const matchConfidence = (score: number) => {
    if (score >= 0.85) return { label: 'High', color: 'text-green-700 bg-green-50 border-green-200' };
    if (score >= 0.7) return { label: 'Good', color: 'text-green-600 bg-green-50 border-green-200' };
    if (score >= 0.5) return { label: 'Moderate', color: 'text-yellow-600 bg-yellow-50 border-yellow-200' };
    if (score >= 0.3) return { label: 'Low', color: 'text-orange-600 bg-orange-50 border-orange-200' };
    return { label: 'Weak', color: 'text-red-600 bg-red-50 border-red-200' };
  };

  const formatPct = (value?: number | null) => `${Math.round((value ?? 0) * 100)}%`;

  const factorLabel = (key: string) => {
    const labels: Record<string, string> = {
      skill_required: 'Required skills',
      skill_optional: 'Optional skills',
      semantic: 'Semantic fit',
      experience: 'Experience',
      seniority: 'Seniority',
      seniority_match: 'Seniority',
      cross_encoder: 'LLM deep rerank',
      base_hybrid: 'Base hybrid score',
      missing_required: 'Missing required penalty',
    };
    return labels[key] || key.replace(/_/g, ' ');
  };

  const modelLabel = (model?: string) => {
    if (!model) return 'Hybrid matching';
    return model.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
  };

  const getScoreWeight = (reasoning: MatchResult['reasoning'], key: string) => {
    const fallback: Record<string, number> = {
      skill_required: 0.35,
      skill_optional: 0.15,
      semantic: 0.20,
      experience: 0.15,
      seniority_match: 0.10,
      cross_encoder: 0.60,
      base_hybrid: 0.40,
    };
    return reasoning?.score_weights?.[key] ?? fallback[key];
  };

  const getRawFactorScore = (reasoning: MatchResult['reasoning'], key: string) => {
    const breakdown = reasoning?.score_breakdown || {};
    const breakdownKey = key === 'seniority_match' ? 'seniority' : key;
    if (breakdown[breakdownKey] !== undefined) return breakdown[breakdownKey];
    if (key === 'skill_required') return reasoning?.required_score;
    if (key === 'skill_optional') return reasoning?.optional_score;
    if (key === 'semantic') return reasoning?.semantic_score;
    if (key === 'experience') return reasoning?.years_score;
    if (key === 'cross_encoder') return reasoning?.cross_encoder_score ?? undefined;
    if (key === 'base_hybrid') return reasoning?.final_score;
    return undefined;
  };

  const getScoreContributions = (reasoning: MatchResult['reasoning']) => {
    if (reasoning?.score_contributions && Object.keys(reasoning.score_contributions).length > 0) {
      return reasoning.score_contributions;
    }
    const breakdown = reasoning?.score_breakdown || {};
    return {
      skill_required: 0.35 * (reasoning?.required_score ?? breakdown.skill_required ?? 0),
      skill_optional: 0.15 * (reasoning?.optional_score ?? breakdown.skill_optional ?? 0),
      semantic: 0.20 * (reasoning?.semantic_score ?? breakdown.semantic ?? 0),
      experience: 0.15 * (reasoning?.years_score ?? breakdown.experience ?? 0),
      seniority_match: 0.10 * (breakdown.seniority ?? 0),
    };
  };

  const renderRankingBasis = (match: MatchResult, compact = false) => {
    const reasoning = match.reasoning;
    const contributions = Object.entries(getScoreContributions(reasoning)).filter(([, value]) => value > 0);
    const penalties = reasoning?.score_penalties && Object.keys(reasoning.score_penalties).length > 0
      ? reasoning.score_penalties
      : reasoning?.missing_penalty
        ? { missing_required: reasoning.missing_penalty }
        : {};
    const penaltyEntries = Object.entries(penalties);
    const formula = reasoning?.scoring_formula || 'Hybrid score built from skills, semantic fit, experience, seniority, and optional LLM reranking.';
    const strengths = reasoning?.strengths ?? [];
    const gaps = reasoning?.gaps ?? [];

    return (
      <div className={`${compact ? 'bg-white border border-gray-200' : 'bg-indigo-50 border border-indigo-100'} rounded-lg p-3`}>
        <div className="flex items-start justify-between gap-3 mb-2">
          <div>
            <h4 className="text-xs font-semibold text-indigo-800 flex items-center gap-1">
              <BarChart3 className="w-3 h-3" /> Ranking basis
            </h4>
            <p className="text-xs text-indigo-700 mt-1">
              Sorted by final ATS score. Model: {modelLabel(reasoning?.scoring_model)}.
            </p>
          </div>
          <span className={`text-sm font-bold ${scoreColor(match.score)}`}>{formatPct(match.score)} final</span>
        </div>

        <p className="text-xs text-gray-600 bg-white/70 border border-white rounded-md p-2 mb-3">{formula}</p>

        {contributions.length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {contributions.map(([key, contribution]) => {
              const rawScore = getRawFactorScore(reasoning, key);
              const weight = getScoreWeight(reasoning, key);
              const contributionPct = Math.round(contribution * 100);
              const width = Math.max(4, Math.min(100, contributionPct));
              return (
                <div key={key} className="bg-white rounded-lg border border-gray-100 p-2">
                  <div className="flex items-center justify-between text-xs mb-1">
                    <span className="font-medium text-gray-700">{factorLabel(key)}</span>
                    <span className="font-semibold text-indigo-700">+{contributionPct} pts</span>
                  </div>
                  <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
                    <div className="h-1.5 bg-indigo-500 rounded-full" style={{ width: `${width}%` }} />
                  </div>
                  <div className="flex items-center justify-between text-[11px] text-gray-500 mt-1">
                    <span>{rawScore !== undefined ? `${formatPct(rawScore)} score` : 'score n/a'}</span>
                    {weight !== undefined && <span>{formatPct(weight)} weight</span>}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {(penaltyEntries.length > 0 || reasoning?.pre_cap_score !== undefined || reasoning?.score_cap !== undefined) && (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-2 mt-3 text-xs">
            {reasoning?.pre_cap_score !== undefined && (
              <div className="bg-white rounded-lg border border-gray-100 p-2">
                <span className="text-gray-500">Before cap</span>
                <strong className="block text-gray-800">{formatPct(reasoning.pre_cap_score)}</strong>
              </div>
            )}
            {penaltyEntries.map(([key, value]) => (
              <div key={key} className="bg-red-50 rounded-lg border border-red-100 p-2">
                <span className="text-red-500">{factorLabel(key)}</span>
                <strong className="block text-red-600">-{formatPct(value)}</strong>
              </div>
            ))}
            {reasoning?.score_cap !== undefined && (
              <div className="bg-white rounded-lg border border-gray-100 p-2">
                <span className="text-gray-500">Required-skill cap</span>
                <strong className="block text-gray-800">{formatPct(reasoning.score_cap)}</strong>
              </div>
            )}
          </div>
        )}

        {reasoning?.score_cap_reason && (
          <p className="text-[11px] text-gray-500 mt-2">{reasoning.score_cap_reason}</p>
        )}

        {(strengths.length > 0 || gaps.length > 0) && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2 mt-3 text-xs">
            {strengths.length > 0 && (
              <div className="bg-green-50 rounded-lg p-2 text-green-700">
                <span className="font-semibold">Strengths:</span> {strengths.join(', ')}
              </div>
            )}
            {gaps.length > 0 && (
              <div className="bg-red-50 rounded-lg p-2 text-red-600">
                <span className="font-semibold">Gaps:</span> {gaps.join(', ')}
              </div>
            )}
          </div>
        )}
      </div>
    );
  };

  const rankBadge = (rank: number) => {
    const colors = ['bg-yellow-400 text-yellow-900', 'bg-gray-300 text-gray-700', 'bg-orange-300 text-orange-800'];
    const color = rank <= 3 ? colors[rank - 1] : 'bg-gray-100 text-gray-500';
    return (
      <span className={`inline-flex items-center justify-center w-7 h-7 rounded-full text-xs font-bold ${color}`}>
        {rank}
      </span>
    );
  };

  const downloadCv = async (candidateId: string, fullName: string | null) => {
    try {
      const response = await api.get(`/candidates/${candidateId}/cv`, {
        params: { download: true },
        responseType: 'blob',
      });
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      const disposition = response.headers?.['content-disposition'] || '';
      const match = disposition.match(/filename="?(.+?)"?$/);
      link.setAttribute('download', match?.[1] || `${fullName || 'CV'}.pdf`);
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch {
      alert('Download not available.');
    }
  };

  const previewMissingSkills = previewCandidate?.match?.reasoning?.missing_required ?? [];
  const previewMatchedSkills = previewCandidate?.match?.reasoning?.matched_required ?? [];

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Candidate Matching</h1>
        {selectedJob && (
          <span className="text-sm text-gray-500">
            <TrendingUp className="w-4 h-4 inline mr-1" />
            {results.length} candidates ranked
          </span>
        )}
      </div>

      {/* ── Job Selection ── */}
      <div className="bg-white rounded-xl shadow-sm border p-6 mb-4">
        <div className="flex gap-3 mb-4">
          <select value={selectedJobId} onChange={(e) => { setSelectedJobId(e.target.value); setResults([]); }}
            className="flex-1 px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 outline-none bg-white">
            <option value="">-- Select a Job --</option>
            {jobs.map((job) => (
              <option key={job.job_id} value={job.job_id}>
                {job.title || 'Untitled'} ({job.seniority || 'any'})
              </option>
            ))}
          </select>
        </div>

        {selectedJob && (
          <div className="text-sm text-gray-600 bg-gray-50 rounded-lg p-3 mb-4">
            <div className="flex items-center gap-2">
              <span className="font-medium">{selectedJob.title}</span>
              {selectedJob.seniority && <span className="px-2 py-0.5 bg-blue-100 text-blue-700 rounded text-xs">{selectedJob.seniority}</span>}
            </div>
            <div className="flex gap-2 mt-2 flex-wrap">
              {(selectedJob.required_skills || []).map((s: string) => (
                <span key={s} className="px-2 py-0.5 bg-blue-50 text-blue-700 rounded text-xs">{s}</span>
              ))}
            </div>
          </div>
        )}

        {/* ── Filters (same as Candidates page) ── */}
        <div className="flex gap-3 flex-wrap items-start">
          <div className="flex-1 min-w-[200px] relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input value={search} onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by name or email..."
              className="w-full pl-9 pr-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 outline-none" />
          </div>

          <div className="relative" ref={skillPickerRef}>
            <button type="button" onClick={() => setShowSkillPicker(!showSkillPicker)}
              className="flex items-center gap-2 px-3 py-2 border rounded-lg hover:bg-gray-50 text-sm">
              <Filter className="w-4 h-4" />
              Skills {selectedSkills.length > 0 && `(${selectedSkills.length})`}
              <ChevronDown className="w-3 h-3" />
            </button>
            {showSkillPicker && (
              <div className="fixed md:absolute top-auto md:top-full left-0 mt-1 w-full md:w-96 bg-white border rounded-xl shadow-lg z-50 p-4 max-h-96 overflow-y-auto">
                <div className="flex justify-between items-center mb-3">
                  <p className="text-sm font-medium text-gray-700">Filter by Skills</p>
                  {selectedSkills.length > 0 && (
                    <button type="button" onClick={() => setSelectedSkills([])}
                      className="text-xs text-blue-600 hover:underline">Clear all</button>
                  )}
                </div>
                <div className="flex items-center gap-2 mb-3 text-xs">
                  <span className="text-gray-500">Logic:</span>
                  <button type="button" onClick={() => setSkillLogic('and')}
                    className={`px-2 py-0.5 rounded ${skillLogic === 'and' ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-600'}`}>AND</button>
                  <button type="button" onClick={() => setSkillLogic('or')}
                    className={`px-2 py-0.5 rounded ${skillLogic === 'or' ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-600'}`}>OR</button>
                </div>
                {Object.entries(skillCategories).map(([category, skills]) => (
                  <div key={category} className="mb-3">
                    <p className="text-xs font-semibold text-gray-500 uppercase mb-1">{category}</p>
                    <div className="flex gap-1 flex-wrap">
                      {skills.map((skill) => (
                        <button key={skill} type="button" onClick={() => toggleSkill(skill)}
                          className={`px-2 py-0.5 rounded text-xs border transition-colors ${
                            selectedSkills.includes(skill)
                              ? 'bg-blue-600 text-white border-blue-600'
                              : 'bg-white text-gray-600 border-gray-200 hover:border-blue-300'
                          }`}>{skill}</button>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="flex items-center gap-2">
            <input value={minYears} onChange={(e) => setMinYears(e.target.value ? Number(e.target.value) : '')}
              type="number" min={0} step="any" placeholder="Min yrs"
              className="w-24 px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 outline-none" />
            <span className="text-gray-400 text-sm">to</span>
            <input value={maxYears} onChange={(e) => setMaxYears(e.target.value ? Number(e.target.value) : '')}
              type="number" min={0} step="any" placeholder="Max yrs"
              className="w-24 px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 outline-none" />
          </div>

          <button type="button" onClick={() => setShowAdvancedFilters(!showAdvancedFilters)}
            className={`flex items-center gap-1 px-3 py-2 border rounded-lg text-sm transition-colors ${
              showAdvancedFilters ? 'bg-blue-50 border-blue-200 text-blue-600' : 'hover:bg-gray-50 text-gray-600'
            }`}>
            <Filter className="w-4 h-4" />
            Advanced
            <ChevronDown className="w-3 h-3" />
          </button>

          {hasFilters && (
            <button type="button" onClick={clearFilters}
              className="flex items-center gap-1 px-3 py-2 border rounded-lg hover:bg-gray-50 text-gray-600 text-sm">
              <X className="w-4 h-4" /> Clear
            </button>
          )}

          <label className="flex items-center gap-1.5 text-xs text-gray-500 cursor-pointer select-none">
            <input type="checkbox" checked={enableCrossEncoder}
              onChange={(e) => setEnableCrossEncoder(e.target.checked)}
              className="rounded accent-blue-600" />
            Enable LLM deep rerank (slower)
          </label>
        </div>

        {showAdvancedFilters && (
          <div className="flex gap-3 flex-wrap items-start mt-4 pt-4 border-t border-gray-100">
            <div className="flex-1 min-w-[180px]">
              <label className="text-xs text-gray-500 mb-1 block">Education</label>
              <input value={educationSearch} onChange={(e) => setEducationSearch(e.target.value)}
                placeholder="Search education..."
                className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 outline-none text-sm" />
            </div>
            <div className="flex-1 min-w-[180px]">
              <label className="text-xs text-gray-500 mb-1 block">University</label>
              <input value={university} onChange={(e) => setUniversity(e.target.value)}
                placeholder="Filter by university..."
                className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 outline-none text-sm" />
            </div>
            <div className="flex-1 min-w-[180px]">
              <label className="text-xs text-gray-500 mb-1 block">Degree</label>
              <input value={degree} onChange={(e) => setDegree(e.target.value)}
                placeholder="Filter by degree..."
                className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 outline-none text-sm" />
            </div>
          </div>
        )}

        <button onClick={handleMatch} disabled={loading || !selectedJobId}
          className="mt-4 w-full flex items-center justify-center gap-2 px-4 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 text-sm font-medium">
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <GitCompare className="w-4 h-4" />}
          {loading ? 'Matching...' : hasFilters ? 'Run Match with Filters' : 'Run Match'}
        </button>
      </div>

      {/* ── Post-match filters ── */}
      {results.length > 0 && (
        <div className="bg-white rounded-xl shadow-sm border p-4 mb-6">
          <div className="flex items-center gap-6 flex-wrap">
            <div className="flex items-center gap-2">
              <label className="text-sm text-gray-600">Min Score:</label>
              <input type="range" min={0} max={100} value={Math.round(minScore * 100)}
                onChange={(e) => setMinScore(Number(e.target.value) / 100)}
                className="w-24 accent-blue-600" />
              <span className="text-sm font-medium w-10">{Math.round(minScore * 100)}%</span>
            </div>
            <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer">
              <input type="checkbox" checked={showOverqualified}
                onChange={(e) => setShowOverqualified(e.target.checked)}
                className="rounded accent-blue-600" />
              Include overqualified
            </label>
            <span className="text-sm text-gray-400 ml-auto">
              <Star className="w-3 h-3 inline mr-1" />
              {filteredResults.length} of {results.length} shown
            </span>
          </div>
        </div>
      )}

      {/* ── Results ── */}
      <div className="space-y-3">
        {loading && (
          <div className="text-center py-12 text-gray-400">
            <Loader2 className="w-8 h-8 mx-auto mb-3 animate-spin" />
            <p>Running semantic matching...</p>
          </div>
        )}

        {error && (
          <div className="bg-red-50 border border-red-200 rounded-xl p-4 mb-4">
            <div className="flex items-start gap-3">
              <AlertTriangle className="w-5 h-5 text-red-500 mt-0.5 flex-shrink-0" />
              <div>
                <p className="text-sm font-medium text-red-800">Matching Error</p>
                <p className="text-sm text-red-600 mt-1">{error}</p>
                <p className="text-xs text-red-500 mt-2">
                  Try running with <strong>cross_encoder_top_k=0</strong> to skip heavy LLM scoring, or check the Ollama server status.
                </p>
              </div>
            </div>
          </div>
        )}

        {paginatedResults.map((r, idx) => {
          const cand = candidates[r.candidate_id];
          const displayName = cand?.full_name || r.candidate_name || `Candidate ${r.candidate_id.slice(0, 8)}`;
          const displayEmail = cand?.email || r.candidate_email;
          const displaySkills = cand?.skills || r.candidate_skills || [];
          const reasoning = r.reasoning ?? {};
          const matchedSkills = reasoning.matched_required ?? [];
          const missingSkills = reasoning.missing_required ?? [];
          const optionalSkills = reasoning.matched_optional ?? [];
          const isOverqualified = reasoning.overqualified;
          const rank = reasoning.rank || idx + 1;
          const pct = Math.round(r.score * 100);
          const confidence = matchConfidence(r.score);
          const isExpanded = expandedAnalysis === r.candidate_id;

          return (
            <div key={r.candidate_id}
              className="bg-white rounded-xl shadow-sm border hover:shadow-md transition-all">
              <div
                className="p-4 cursor-pointer"
                onClick={() => setPreviewCandidate({ ...(cand || {
                  candidate_id: r.candidate_id,
                  full_name: r.candidate_name || null,
                  email: r.candidate_email || null,
                  phone: null,
                  skills: r.candidate_skills || [],
                  experience: [],
                  education: [],
                  projects: [],
                  total_years_experience: r.candidate_total_years_experience ?? null,
                  raw_text: '',
                }), match: r })}
              >
                <div className="flex items-center gap-4">
                  {rankBadge(rank)}

                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-gray-900">
                        {displayName}
                      </span>
                      <span className={`px-2 py-0.5 rounded-full text-xs border font-medium ${confidence.color}`}>
                        {confidence.label}
                      </span>
                      {displayEmail && <span className="text-xs text-gray-400 hidden sm:inline">{displayEmail}</span>}
                      {isOverqualified && (
                        <span className="flex items-center gap-1 px-1.5 py-0.5 bg-orange-100 text-orange-700 rounded text-xs">
                          <AlertTriangle className="w-3 h-3" /> Overqualified
                        </span>
                      )}
                    </div>

                    <div className="flex gap-1 flex-wrap mt-1.5">
                      {displaySkills.slice(0, 8).map((s: string) => {
                        const isMatched = matchedSkills.includes(s);
                        return (
                          <span key={s} className={`inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-xs ${
                            isMatched ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'
                          }`}>
                            {isMatched ? <CheckCircle2 className="w-2.5 h-2.5" /> : null}
                            {s}
                          </span>
                        );
                      })}
                      {displaySkills.length > 8 && (
                        <span className="text-xs text-gray-400">+{displaySkills.length - 8}</span>
                      )}
                    </div>

                    {missingSkills.length > 0 && (
                      <div className="flex items-center gap-1 mt-1">
                        <XCircle className="w-3 h-3 text-red-400" />
                        <span className="text-xs text-red-400">Missing: </span>
                        {missingSkills.slice(0, 5).map((s: string) => (
                          <span key={s} className="px-1.5 py-0.5 bg-red-50 text-red-500 rounded text-xs">{s}</span>
                        ))}
                        {missingSkills.length > 5 && (
                          <span className="text-xs text-red-300">+{missingSkills.length - 5}</span>
                        )}
                      </div>
                    )}
                  </div>

                  <div className="text-right flex flex-col items-end gap-1.5 flex-shrink-0">
                    <div className="relative w-14 h-14">
                      <svg className="w-14 h-14 -rotate-90" viewBox="0 0 36 36">
                        <circle cx="18" cy="18" r="16" fill="none" stroke="#e5e7eb" strokeWidth="3" />
                        <circle cx="18" cy="18" r="16" fill="none"
                          className={scoreRing(r.score)}
                          strokeWidth="3"
                          strokeDasharray={`${pct * 0.5027} 50.27`}
                          strokeLinecap="round" />
                      </svg>
                      <span className={`absolute inset-0 flex items-center justify-center text-sm font-bold ${scoreColor(r.score)}`}>
                        {pct}%
                      </span>
                    </div>
                    <div className="text-[10px] text-gray-400 space-y-0.5">
                      {reasoning.estimated_years !== undefined && <div>~{reasoning.estimated_years}y exp</div>}
                      {reasoning.skill_score !== undefined && <div>Match: {Math.round(reasoning.skill_score * 100)}%</div>}
                    </div>
                  </div>
                </div>
              </div>

              <div className="border-t border-gray-100">
                <button
                  onClick={() => setExpandedAnalysis(isExpanded ? null : r.candidate_id)}
                  className="w-full flex items-center justify-between px-4 py-2 text-xs text-gray-500 hover:bg-gray-50 transition-colors"
                >
                  <span className="flex items-center gap-1">
                    <Brain className="w-3 h-3" />
                    {isExpanded ? 'Hide' : 'Show'} ranking basis
                  </span>
                  {isExpanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                </button>

                {isExpanded && (
                  <div className="px-4 pb-4 pt-2 space-y-3 border-t border-gray-50">
                    {renderRankingBasis(r)}

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      <div className="bg-gray-50 rounded-lg p-3">
                        <h4 className="text-xs font-semibold text-gray-700 mb-2 flex items-center gap-1">
                          <BarChart3 className="w-3 h-3" /> Required Skills Match
                        </h4>
                        <div className="flex items-center gap-2 mb-1">
                          <div className="flex-1 bg-gray-200 rounded-full h-2">
                            <div className={`h-2 rounded-full ${scoreBg(reasoning.required_score || 0)}`}
                              style={{ width: `${Math.round((reasoning.required_score || 0) * 100)}%` }} />
                          </div>
                          <span className="text-xs font-medium">{Math.round((reasoning.required_score || 0) * 100)}%</span>
                        </div>
                        <p className="text-xs text-gray-500">{matchedSkills.length} of {(reasoning.matched_required?.length || 0) + (reasoning.missing_required?.length || 0)} matched</p>
                      </div>

                      <div className="bg-gray-50 rounded-lg p-3">
                        <h4 className="text-xs font-semibold text-gray-700 mb-2 flex items-center gap-1">
                          <BarChart3 className="w-3 h-3" /> Optional Skills Match
                        </h4>
                        <div className="flex items-center gap-2 mb-1">
                          <div className="flex-1 bg-gray-200 rounded-full h-2">
                            <div className={`h-2 rounded-full ${scoreBg(reasoning.optional_score || 0)}`}
                              style={{ width: `${Math.round((reasoning.optional_score || 0) * 100)}%` }} />
                          </div>
                          <span className="text-xs font-medium">{Math.round((reasoning.optional_score || 0) * 100)}%</span>
                        </div>
                        <p className="text-xs text-gray-500">{optionalSkills.length} optional matched</p>
                      </div>

                      <div className="bg-gray-50 rounded-lg p-3">
                        <h4 className="text-xs font-semibold text-gray-700 mb-2 flex items-center gap-1">
                          <TrendingUp className="w-3 h-3" /> Overall ATS Score
                        </h4>
                        <div className="flex items-center gap-2">
                          <div className="flex-1 bg-gray-200 rounded-full h-2.5">
                            <div className={`h-2.5 rounded-full ${scoreBg(r.score)}`}
                              style={{ width: `${pct}%` }} />
                          </div>
                          <span className={`text-sm font-bold ${scoreColor(r.score)}`}>{pct}%</span>
                        </div>
                        <p className="text-xs text-gray-500 mt-1">Weighted scoring from the ranking basis above</p>
                      </div>

                      <div className="bg-gray-50 rounded-lg p-3">
                        <h4 className="text-xs font-semibold text-gray-700 mb-2">Match Factors</h4>
                        <div className="space-y-1">
                          <div className="flex items-center justify-between text-xs">
                            <span className="text-gray-500">Cross-Encoder</span>
                            <span className="font-medium">{reasoning.used_cross_encoder ? 'Yes' : 'Quick score'}</span>
                          </div>
                          <div className="flex items-center justify-between text-xs">
                            <span className="text-gray-500">Required Skills</span>
                            <span className="font-medium">{Math.round((reasoning.required_score || 0) * 100)}%</span>
                          </div>
                          <div className="flex items-center justify-between text-xs">
                            <span className="text-gray-500">Optional Skills</span>
                            <span className="font-medium">{Math.round((reasoning.optional_score || 0) * 100)}%</span>
                          </div>
                          {reasoning.estimated_years !== undefined && (
                            <div className="flex items-center justify-between text-xs">
                              <span className="text-gray-500">Experience</span>
                              <span className="font-medium">{reasoning.estimated_years}y</span>
                            </div>
                          )}
                        </div>
                      </div>
                    </div>

                    <div className="bg-green-50 rounded-lg p-3">
                      <h4 className="text-xs font-semibold text-green-700 mb-1.5 flex items-center gap-1">
                        <CheckCircle2 className="w-3 h-3" /> Why this candidate matched
                      </h4>
                      <ul className="text-xs text-green-600 space-y-0.5">
                        {matchedSkills.length > 0 && (
                          <li>• Matched {matchedSkills.length} required skills: {matchedSkills.join(', ')}</li>
                        )}
                        {optionalSkills.length > 0 && (
                          <li>• Brings {optionalSkills.length} optional skills: {optionalSkills.join(', ')}</li>
                        )}
                        {reasoning.estimated_years !== undefined && reasoning.estimated_years > 0 && (
                          <li>• Has ~{reasoning.estimated_years} years of relevant experience</li>
                        )}
                      </ul>
                    </div>

                    {missingSkills.length > 0 && (
                      <div className="bg-red-50 rounded-lg p-3">
                        <h4 className="text-xs font-semibold text-red-600 mb-1.5 flex items-center gap-1">
                          <XCircle className="w-3 h-3" /> Missing Skills
                        </h4>
                        <div className="flex gap-1 flex-wrap">
                          {missingSkills.map((s: string) => (
                            <span key={s} className="px-2 py-0.5 bg-red-100 text-red-600 rounded text-xs">{s}</span>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          );
        })}

        {!loading && filteredResults.length > perPage && paginatedResults.length < filteredResults.length && (
          <div className="text-center pt-2">
            <button onClick={() => setPage(p => p + 1)}
              className="px-4 py-2 text-sm text-blue-600 border border-blue-200 rounded-lg hover:bg-blue-50">
              Show more ({filteredResults.length - paginatedResults.length} remaining)
            </button>
          </div>
        )}

        {!loading && filteredResults.length === 0 && (
          <div className="text-center py-12 text-gray-400">
            <GitCompare className="w-12 h-12 mx-auto mb-3 opacity-50" />
            <p>{results.length > 0 ? 'No candidates match the current filters.' : 'Select a job and click Match.'}</p>
          </div>
        )}
      </div>

      {previewCandidate && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4"
          onClick={() => setPreviewCandidate(null)}>
          <div className="bg-white rounded-xl shadow-xl w-full max-w-2xl max-h-[85vh] flex flex-col"
            onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between p-5 border-b">
              <div>
                <h2 className="text-lg font-bold text-gray-900">{previewCandidate.full_name || 'Unknown'}</h2>
                <p className="text-sm text-gray-500">{previewCandidate.email}</p>
              </div>
              <div className="flex items-center gap-2">
                <button onClick={() => downloadCv(previewCandidate.candidate_id, previewCandidate.full_name)}
                  className="flex items-center gap-1 px-3 py-2 border rounded-lg hover:bg-blue-50 text-blue-600 text-sm">
                  <Download className="w-4 h-4" /> CV
                </button>
                <button onClick={() => setPreviewCandidate(null)}
                  className="p-2 hover:bg-gray-100 rounded-lg">
                  <X className="w-5 h-5 text-gray-500" />
                </button>
              </div>
            </div>
            <div className="flex-1 overflow-y-auto p-5 space-y-4">
              {previewCandidate.match && (
                <div className="bg-blue-50 rounded-lg p-4">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-sm font-semibold text-blue-800">ATS Match Score</span>
                    <span className={`text-2xl font-bold ${scoreColor(previewCandidate.match.score)}`}>
                      {Math.round(previewCandidate.match.score * 100)}%
                    </span>
                  </div>
                  <div className="w-full bg-blue-100 rounded-full h-2.5 mb-3">
                    <div className={`h-2.5 rounded-full ${scoreBg(previewCandidate.match.score)}`}
                      style={{ width: `${Math.round(previewCandidate.match.score * 100)}%` }} />
                  </div>
                  <div className="grid grid-cols-2 gap-3 text-sm">
                    <div><span className="text-gray-500">Rank:</span> <span className="font-medium">#{previewCandidate.match.reasoning?.rank || '-'}</span></div>
                    <div><span className="text-gray-500">Experience:</span> <span className="font-medium">{previewCandidate.match.reasoning?.estimated_years || '-'}y</span></div>
                    <div><span className="text-gray-500">Required Skills:</span> <span className="font-medium">{Math.round((previewCandidate.match.reasoning?.required_score || 0) * 100)}%</span></div>
                    <div><span className="text-gray-500">Optional Skills:</span> <span className="font-medium">{Math.round((previewCandidate.match.reasoning?.optional_score || 0) * 100)}%</span></div>
                  </div>
                </div>
              )}
              {previewCandidate.match && renderRankingBasis(previewCandidate.match, true)}
              <div>
                <h3 className="text-sm font-semibold text-gray-700 mb-2">Skills</h3>
                <div className="flex gap-1.5 flex-wrap">
                  {(previewCandidate.skills || []).map((s: string) => (
                    <span key={s} className="px-2.5 py-1 bg-blue-50 text-blue-700 rounded-lg text-xs font-medium">{s}</span>
                  ))}
                </div>
              </div>
              {previewMissingSkills.length > 0 && (
                <div>
                  <h3 className="text-sm font-semibold text-red-600 mb-2">Missing Skills</h3>
                  <div className="flex gap-1.5 flex-wrap">
                    {previewMissingSkills.map((s) => (
                      <span key={s} className="px-2.5 py-1 bg-red-50 text-red-600 rounded-lg text-xs">{s}</span>
                    ))}
                  </div>
                </div>
              )}
              {previewMatchedSkills.length > 0 && (
                <div>
                  <h3 className="text-sm font-semibold text-green-600 mb-2">Matched Skills</h3>
                  <div className="flex gap-1.5 flex-wrap">
                    {previewMatchedSkills.map((s) => (
                      <span key={s} className="px-2.5 py-1 bg-green-50 text-green-600 rounded-lg text-xs">{s}</span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
