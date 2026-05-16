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
  total_questions?: number;
  is_completed?: boolean;
}

export interface InterviewEvaluation {
  overall_score: number;
  feedback?: string;
  strengths: string[];
  weaknesses: string[];
  skill_scores?: Record<string, number>;
  answered_questions?: number;
  total_questions?: number;
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
