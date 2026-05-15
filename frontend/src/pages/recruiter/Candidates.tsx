import { useState, useEffect, useCallback, useRef } from 'react';
import api from '../../api/client';
import { Upload, User, Search, X, Briefcase, ChevronDown, Eye, Award, Filter, Star, Trash2, AlertTriangle, Download, Loader2, FileText } from 'lucide-react';
import type { Candidate, SkillCategory } from '../../types/api';
import { getApiErrorMessage, getApiStatus } from '../../utils/errors';

export default function Candidates() {
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [search, setSearch] = useState('');
  const [selectedSkills, setSelectedSkills] = useState<string[]>([]);
  const [skillCategories, setSkillCategories] = useState<SkillCategory>({});
  const [showSkillPicker, setShowSkillPicker] = useState(false);
  const [minSkills, setMinSkills] = useState<number | ''>('');
  const [minYears, setMinYears] = useState<number | ''>('');
  const [maxYears, setMaxYears] = useState<number | ''>('');
  const [sortBy, setSortBy] = useState('newest');
  const [skillLogic, setSkillLogic] = useState<'and' | 'or'>('and');
  const [educationSearch, setEducationSearch] = useState('');
  const [university, setUniversity] = useState('');
  const [degree, setDegree] = useState('');
  const [showAdvancedFilters, setShowAdvancedFilters] = useState(false);
  const [previewCandidate, setPreviewCandidate] = useState<Candidate | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);
  const [deleteAllConfirm, setDeleteAllConfirm] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [cvContent, setCvContent] = useState<string | null>(null);
  const skillPickerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.get<SkillCategory>('/skills/categories').then(({ data }) => setSkillCategories(data)).catch(() => {
      // Skill filters are optional; the candidate list still works without them.
    });
  }, []);

  const loadCandidates = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string> = {};
      if (search) params.search = search;
      if (selectedSkills.length > 0) { params.skills = selectedSkills.join(','); params.skill_logic = skillLogic; }
      if (minSkills !== '' && Number(minSkills) > 0) params.min_skills = String(minSkills);
      if (minYears !== '') params.min_years = String(minYears);
      if (maxYears !== '') params.max_years = String(maxYears);
      if (educationSearch) params.education_search = educationSearch;
      if (university) params.university = university;
      if (degree) params.degree = degree;
      if (sortBy === 'name') { params.sort_by = 'name'; params.sort_dir = 'asc'; }
      else if (sortBy === 'experience') { params.sort_by = 'experience'; params.sort_dir = 'desc'; }
      else if (sortBy === 'skills') { params.sort_by = 'skills'; params.sort_dir = 'desc'; }
      else if (sortBy === 'education') { params.sort_by = 'education'; params.sort_dir = 'desc'; }
      const { data } = await api.get<Candidate[]>('/candidates', { params });
      setCandidates(Array.isArray(data) ? data : []);
    } catch {
      setCandidates([]);
    } finally {
      setLoading(false);
    }
  }, [search, selectedSkills, skillLogic, minSkills, minYears, maxYears, educationSearch, university, degree, sortBy]);

  useEffect(() => {
    const refresh = async () => {
      await loadCandidates();
    };
    void refresh();
  }, [loadCandidates]);

  const waitForUploadTask = async (taskId: string) => {
    for (let attempt = 0; attempt < 180; attempt += 1) {
      const { data } = await api.get(`/candidates/async/${taskId}`);
      if (data.status === 'completed') return;
      if (data.status === 'failed') throw new Error(data.error || 'Upload failed');
      await new Promise((resolve) => setTimeout(resolve, 2000));
    }
    throw new Error('Upload processing timed out');
  };

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const { data } = await api.post('/candidates/async', formData);
      await waitForUploadTask(data.task_id);
      await loadCandidates();
    } catch (err: unknown) {
      alert(getApiErrorMessage(err, 'Upload failed'));
    } finally { setUploading(false); }
  };

  const toggleSkill = (skill: string) => {
    setSelectedSkills((prev) =>
      prev.includes(skill) ? prev.filter((s) => s !== skill) : [...prev, skill]
    );
  };

  const clearFilters = () => {
    setSearch('');
    setSelectedSkills([]);
    setSkillLogic('and');
    setMinSkills('');
    setMinYears('');
    setMaxYears('');
    setEducationSearch('');
    setUniversity('');
    setDegree('');
    setSortBy('newest');
  };

  const handleDelete = async (candidateId: string) => {
    setDeleting(candidateId);
    try {
      await api.delete(`/candidates/${candidateId}`);
      setDeleteConfirm(null);
      await loadCandidates();
    } catch (err: unknown) {
      alert(getApiErrorMessage(err, 'Delete failed'));
    } finally {
      setDeleting(null);
    }
  };

  const handleDeleteAll = async () => {
    try {
      await api.delete('/candidates');
      setDeleteAllConfirm(false);
      await loadCandidates();
    } catch (err: unknown) {
      alert(getApiErrorMessage(err, 'Delete all failed'));
    }
  };

  const openPreview = async (candidate: Candidate) => {
    setPreviewCandidate(candidate);
    setPreviewLoading(true);
    setPreviewError(null);
    setCvContent(null);
    try {
      const { data } = await api.get(`/candidates/${candidate.candidate_id}/cv`, { responseType: 'text' });
      setCvContent(typeof data === 'string' ? data : 'CV content loaded');
    } catch (err: unknown) {
      if (getApiStatus(err) === 404) {
        setPreviewError('No CV content available for this candidate.');
      } else {
        setPreviewError('Failed to load CV. Please try again.');
      }
    } finally {
      setPreviewLoading(false);
    }
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
      alert('CV file download is not available.');
    }
  };

  const hasFilters = search || selectedSkills.length > 0 || minSkills !== '' || minYears !== '' || maxYears !== '' || educationSearch || university || degree;

  const handleFilter = (e: React.FormEvent) => {
    e.preventDefault();
    loadCandidates();
  };

  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (skillPickerRef.current && !skillPickerRef.current.contains(e.target as Node)) {
        setShowSkillPicker(false);
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  const scoreBadge = (score: number | null) => {
    if (score == null) return null;
    const pct = Math.min(score * 100, 100);
    let color = 'bg-red-100 text-red-700';
    if (pct >= 70) color = 'bg-green-100 text-green-700';
    else if (pct >= 40) color = 'bg-yellow-100 text-yellow-700';
    return (
      <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${color}`}>
        <Star className="w-3 h-3" />
        {pct.toFixed(0)}%
      </span>
    );
  };

  const highlightText = (text: string, query: string) => {
    if (!query.trim()) return text;
    const parts = text.split(new RegExp(`(${query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi'));
    return parts.map((part, i) =>
      part.toLowerCase() === query.toLowerCase()
        ? <mark key={i} className="bg-yellow-200 rounded px-0.5">{part}</mark>
        : part
    );
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Candidates</h1>
        <div className="flex items-center gap-3">
          <select value={sortBy} onChange={(e) => setSortBy(e.target.value)}
            className="px-3 py-2 border rounded-lg text-sm outline-none focus:ring-2 focus:ring-blue-500 bg-white">
            <option value="newest">Newest First</option>
            <option value="name">Name (A-Z)</option>
            <option value="experience">Most Experience</option>
            <option value="skills">Most Skills</option>
            <option value="education">Highest Education</option>
          </select>
          {candidates.length > 0 && !deleteAllConfirm && (
            <button onClick={() => setDeleteAllConfirm(true)}
              className="flex items-center gap-2 px-3 py-2 bg-red-50 text-red-600 border border-red-200 rounded-lg hover:bg-red-100 text-sm">
              <Trash2 className="w-4 h-4" />
              Delete All
            </button>
          )}
          {deleteAllConfirm && (
            <div className="flex items-center gap-2 px-3 py-2 bg-red-50 border border-red-300 rounded-lg">
              <AlertTriangle className="w-4 h-4 text-red-500" />
              <span className="text-sm text-red-700">Delete ALL {candidates.length} candidates?</span>
              <button onClick={() => setDeleteAllConfirm(false)}
                className="px-2 py-1 text-sm text-gray-600 hover:text-gray-800">Cancel</button>
              <button onClick={handleDeleteAll}
                className="px-2 py-1 text-sm bg-red-600 text-white rounded hover:bg-red-700">Confirm</button>
            </div>
          )}
          <label className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 cursor-pointer disabled:opacity-50">
            <Upload className="w-4 h-4" />
            {uploading ? 'Uploading...' : 'Upload CV'}
            <input type="file" accept=".pdf,.docx,.doc,.txt" onChange={handleUpload} className="hidden" disabled={uploading} />
          </label>
        </div>
      </div>

      <form onSubmit={handleFilter} className="bg-white rounded-xl shadow-sm border p-4 mb-6">
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

          <button type="submit"
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm">Filter</button>
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
      </form>

      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {[1, 2, 3, 4, 5, 6].map((i) => (
            <div key={i} className="bg-white rounded-xl shadow-sm border p-5 animate-pulse">
              <div className="flex items-start gap-3 mb-3">
                <div className="w-10 h-10 bg-gray-200 rounded-full" />
                <div className="flex-1">
                  <div className="h-4 bg-gray-200 rounded w-3/4 mb-2" />
                  <div className="h-3 bg-gray-200 rounded w-1/2" />
                </div>
              </div>
              <div className="flex gap-2 flex-wrap mb-3">
                {[1, 2, 3].map((j) => (
                  <div key={j} className="h-5 bg-gray-200 rounded w-14" />
                ))}
              </div>
              <div className="h-3 bg-gray-200 rounded w-1/3" />
            </div>
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {candidates.map((c) => (
            <div key={c.candidate_id}
              className="bg-white rounded-xl shadow-sm border p-5 hover:shadow-md hover:border-blue-200 transition-all relative group cursor-pointer"
              onClick={() => openPreview(c)}>
              {deleteConfirm === c.candidate_id ? (
                <div className="absolute inset-0 bg-white/95 rounded-xl flex flex-col items-center justify-center z-10 p-4"
                  onClick={(e) => e.stopPropagation()}>
                  <AlertTriangle className="w-8 h-8 text-red-500 mb-2" />
                  <p className="text-sm font-medium text-gray-800 mb-1">Delete this candidate?</p>
                  <p className="text-xs text-gray-500 mb-3 text-center">{c.full_name || 'Unknown'}<br />{c.email || 'No email'}</p>
                  <div className="flex gap-2">
                    <button onClick={() => setDeleteConfirm(null)}
                      className="px-3 py-1.5 text-sm border rounded-lg hover:bg-gray-50">Cancel</button>
                    <button onClick={() => handleDelete(c.candidate_id)}
                      disabled={deleting === c.candidate_id}
                      className="px-3 py-1.5 text-sm bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50">
                      {deleting === c.candidate_id ? 'Deleting...' : 'Delete'}
                    </button>
                  </div>
                </div>
              ) : null}
              <div className="flex items-start gap-3 mb-3">
                <div className="w-10 h-10 bg-blue-100 rounded-full flex items-center justify-center flex-shrink-0">
                  <User className="w-5 h-5 text-blue-600" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <h3 className="font-semibold text-gray-900 truncate">
                      {search ? highlightText(c.full_name || 'Unknown', search) : (c.full_name || 'Unknown')}
                    </h3>
                    {scoreBadge(c.total_years_experience != null ? c.total_years_experience / 20 : null)}
                  </div>
                  <p className="text-xs text-gray-500 truncate">
                    {search ? highlightText(c.email || '', search) : c.email}
                  </p>
                </div>
                <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                  <button onClick={(e) => { e.stopPropagation(); downloadCv(c.candidate_id, c.full_name); }}
                    className="p-1.5 hover:bg-blue-50 rounded-lg" title="Download CV">
                    <Download className="w-4 h-4 text-gray-400 hover:text-blue-600" />
                  </button>
                  <button onClick={(e) => { e.stopPropagation(); setDeleteConfirm(c.candidate_id); }}
                    className="p-1.5 hover:bg-red-50 rounded-lg" title="Delete">
                    <Trash2 className="w-4 h-4 text-gray-400 hover:text-red-500" />
                  </button>
                </div>
                {c.total_years_experience != null && (
                  <div className="flex items-center gap-1 text-xs bg-gray-100 text-gray-600 rounded px-2 py-1">
                    <Briefcase className="w-3 h-3" />
                    {c.total_years_experience}y
                  </div>
                )}
              </div>
              <div className="flex gap-1 flex-wrap">
                {(c.skills || []).slice(0, 8).map((s) => (
                  <span key={s} className={`px-2 py-0.5 rounded text-xs ${
                    selectedSkills.includes(s) ? 'bg-blue-100 text-blue-700' : 'bg-gray-100 text-gray-600'
                  }`}>{s}</span>
                ))}
                {(c.skills || []).length > 8 && (
                  <span className="text-xs text-gray-400">+{c.skills.length - 8}</span>
                )}
              </div>
              <div className="flex items-center gap-3 mt-3 text-xs text-gray-400">
                <span className="flex items-center gap-1"><Briefcase className="w-3 h-3" />{(c.experience || []).length} entries</span>
                <span className="flex items-center gap-1"><Eye className="w-3 h-3" />Preview</span>
              </div>
            </div>
          ))}
          {candidates.length === 0 && (
            <div className="col-span-full text-center py-12 text-gray-400">
              <User className="w-12 h-12 mx-auto mb-3 opacity-50" />
              <p>{hasFilters ? 'No candidates match the filters.' : 'No candidates yet. Upload a CV to get started.'}</p>
            </div>
          )}
        </div>
      )}

      {previewCandidate && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4"
          onClick={() => { setPreviewCandidate(null); setPreviewError(null); setCvContent(null); }}>
          <div className="bg-white rounded-xl shadow-xl w-full max-w-3xl max-h-[85vh] flex flex-col"
            onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between p-5 border-b">
              <div>
                <h2 className="text-lg font-bold text-gray-900">{previewCandidate.full_name || 'Unknown'}</h2>
                <p className="text-sm text-gray-500">{previewCandidate.email} {previewCandidate.phone ? `· ${previewCandidate.phone}` : ''}</p>
              </div>
              <div className="flex items-center gap-2">
                <button onClick={() => downloadCv(previewCandidate.candidate_id, previewCandidate.full_name)}
                  className="flex items-center gap-1 px-3 py-2 border rounded-lg hover:bg-blue-50 text-blue-600 text-sm">
                  <Download className="w-4 h-4" /> Download CV
                </button>
                <button onClick={() => { setPreviewCandidate(null); setPreviewError(null); setCvContent(null); }}
                  className="p-2 hover:bg-gray-100 rounded-lg">
                  <X className="w-5 h-5 text-gray-500" />
                </button>
              </div>
            </div>

            <div className="flex-1 overflow-y-auto p-5 space-y-5">
              <div>
                <h3 className="text-sm font-semibold text-gray-700 flex items-center gap-2 mb-2">
                  <Award className="w-4 h-4 text-blue-500" /> Skills
                </h3>
                <div className="flex gap-1.5 flex-wrap">
                  {(previewCandidate.skills || []).map((s) => (
                    <span key={s} className="px-2.5 py-1 bg-blue-50 text-blue-700 rounded-lg text-xs font-medium">{s}</span>
                  ))}
                </div>
              </div>

              <div>
                <h3 className="text-sm font-semibold text-gray-700 flex items-center gap-2 mb-2">
                  <Briefcase className="w-4 h-4 text-gray-400" /> Experience
                </h3>
                {previewCandidate.total_years_experience != null && (
                  <div className="flex items-center gap-2 text-sm mb-2">
                    <span className="font-medium">{previewCandidate.total_years_experience} years total</span>
                  </div>
                )}
                {(previewCandidate.experience || []).length > 0 ? (
                  <ul className="space-y-1">
                    {previewCandidate.experience.map((exp, i) => (
                      <li key={i} className="text-sm text-gray-600 bg-gray-50 rounded-lg px-3 py-2">{exp}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-gray-400 italic">No experience entries parsed.</p>
                )}
              </div>

              {(previewCandidate.education || []).length > 0 && (
                <div>
                  <h3 className="text-sm font-semibold text-gray-700 mb-2">Education</h3>
                  <ul className="space-y-1">
                    {previewCandidate.education.map((edu, i) => (
                      <li key={i} className="text-sm text-gray-600 bg-gray-50 rounded-lg px-3 py-2">{edu}</li>
                    ))}
                  </ul>
                </div>
              )}

              <div>
                <h3 className="text-sm font-semibold text-gray-700 flex items-center gap-2 mb-2">
                  <FileText className="w-4 h-4 text-gray-400" /> CV Content
                </h3>
                {previewLoading ? (
                  <div className="flex items-center gap-2 text-sm text-gray-400 bg-gray-50 rounded-lg p-4">
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Loading CV...
                  </div>
                ) : previewError ? (
                  <div className="flex items-center gap-2 text-sm text-red-500 bg-red-50 rounded-lg p-4">
                    <AlertTriangle className="w-4 h-4" />
                    {previewError}
                  </div>
                ) : (
                  <pre className="text-xs text-gray-500 bg-gray-50 rounded-lg p-4 whitespace-pre-wrap max-h-48 overflow-y-auto leading-relaxed">
                    {cvContent?.slice(0, 5000) || 'No content'}
                  </pre>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
