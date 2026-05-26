export interface Job {
  job_id: string;
  title?: string | null;
  description?: string;
  required_skills?: string[];
  optional_skills?: string[];
  seniority?: string | null;
}

export interface Candidate {
  candidate_id: string;
  full_name: string | null;
  email: string | null;
  phone: string | null;
  skills: string[];
  experience: string[];
  education: string[];
  projects: string[];
  total_years_experience: number | null;
  raw_text: string;
  cv_url?: string | null;
}

export interface SkillCategory {
  [category: string]: string[];
}

export interface MatchReasoning {
  rank?: number;
  similarity?: number;
  skill_score?: number;
  required_score?: number;
  optional_score?: number;
  semantic_score?: number;
  cross_encoder_score?: number | null;
  years_score?: number;
  missing_penalty?: number;
  matched_required?: string[];
  missing_required?: string[];
  matched_optional?: string[];
  estimated_years?: number;
  overqualified?: boolean;
  used_cross_encoder?: boolean;
  scoring_model?: string;
  scoring_formula?: string;
  score_breakdown?: Record<string, number>;
  score_weights?: Record<string, number>;
  score_contributions?: Record<string, number>;
  score_penalties?: Record<string, number>;
  score_trace?: Record<string, unknown>;
  pre_cap_score?: number;
  score_cap?: number;
  score_cap_reason?: string;
  final_score?: number;
  esco_coverage?: number;
  seniority_match?: string;
  strengths?: string[];
  gaps?: string[];
  recommendations?: string[];
}

export interface MatchResult {
  candidate_id: string;
  candidate_name?: string | null;
  candidate_email?: string | null;
  candidate_skills?: string[];
  candidate_total_years_experience?: number | null;
  score: number;
  reasoning?: MatchReasoning;
}

export interface InterviewQuestion {
  id?: string;
  question_id?: string;
  skill?: string;
  question?: string;
  question_text?: string;
  difficulty?: string;
  category?: string;
  expected_answer_hint?: string;
  evaluation_criteria?: string[];
  tags?: string[];
}

export interface InterviewSessionResponse {
  session_id: string;
  candidate_name?: string;
  job_title?: string;
  questions: InterviewQuestion[];
  status?: string;
  answered_count?: number;
  answered_question_ids?: string[];
  current_question_id?: string | null;
  total_questions?: number;
  is_completed?: boolean;
}

export interface InterviewEvaluation {
  session_id?: string;
  status?: string;
  is_completed?: boolean;
  overall_score: number;
  feedback?: string;
  strengths: string[];
  weaknesses: string[];
  skill_scores?: Record<string, number>;
  languages_used?: string[];
  answered_questions?: number;
  total_questions?: number;
}

export interface InterviewAnswerSummary {
  question_id: string;
  skill: string;
  answer: string;
  score: number;
  feedback: string;
}

export interface InterviewSessionStatus {
  session_id: string;
  job_id: string;
  candidate_id: string;
  status: string;
  answers_count: number;
  questions: InterviewQuestion[];
  answers: InterviewAnswerSummary[];
  average_score?: number | null;
}

export interface PublicInterviewAnswerResponse {
  question_id: string;
  skill: string;
  question: string;
  answer: string;
  score: number;
  feedback: string;
  language_detected: string;
  strengths: string[];
  weaknesses: string[];
  using_llm: boolean;
  evaluation_status?: string;
  next_question?: InterviewQuestion | null;
}

export interface DashboardInterviewResult {
  session_id?: string | null;
  report_id?: string | null;
  candidate_id: string;
  candidate_name?: string | null;
  job_id: string;
  job_title?: string | null;
  status: string;
  analysis_status: 'in_progress' | 'queued' | 'analyzing' | 'ready' | string;
  interview_score: number;
  match_score?: number | null;
  report_score?: number | null;
  answered_questions: number;
  total_questions: number;
}

export interface SkillGapItem {
  skill: string;
  matched: boolean;
  required: boolean;
}

export interface ReportResponse {
  candidate_name?: string;
  job_title?: string;
  score_breakdown: {
    overall_score: number;
    similarity_score: number;
    required_skills_score: number;
    optional_skills_score: number;
    scoring_model?: string | null;
    scoring_formula?: string | null;
    score_weights?: Record<string, number>;
    score_contributions?: Record<string, number>;
    score_penalties?: Record<string, number>;
    pre_cap_score?: number | null;
    score_cap?: number | null;
    score_cap_reason?: string | null;
    score_trace?: Record<string, unknown>;
  };
  skill_gap: {
    items: SkillGapItem[];
  };
  skill_scores?: Record<string, number>;
  recommendation?: string;
  strengths: string[];
  weaknesses: string[];
}

export interface CandidateUploadResult {
  full_name?: string | null;
  email?: string | null;
  skills?: string[];
  task_id?: string;
  status?: string;
  error?: string;
  type?: string;
}

export type ApiParams = Record<string, string | number | boolean>;
