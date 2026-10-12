// src/types.ts — "TẦNG THỨ 4" của hệ schema: interface TypeScript phản chiếu
// 1-1 các Pydantic response model của backend (đã serialize camelCase).
//
// Nguồn sự thật: app/models/schemas.py. Đổi schema bên đó thì PHẢI đổi ở đây —
// bù lại, mọi chỗ frontend gõ sai tên field sẽ đỏ ngay lúc compile chứ không
// âm thầm undefined lúc chạy.

// ---- Enum (khớp giá trị string của (str, Enum) + mode="json") ----
export type Verdict =
  | 'strong_match'
  | 'good_match'
  | 'partial_match'
  | 'weak_match'
  | 'not_a_match'

export type Priority = 'high' | 'medium' | 'low'

export type ResourceKind = 'docs' | 'roadmap' | 'course' | 'search'

// ---- Upload & quản lý CV ----
export interface ChunkPreview {
  chunkId: string
  section: string
  charCount: number
  preview: string
}

export interface CVUploadResponse {
  cvId: string
  filename: string
  totalChunks: number
  sectionsDetected: string[]
  chunks: ChunkPreview[]
  createdAt: string // ISO datetime — backend serialize datetime thành string
}

export interface CVListItem {
  cvId: string
  filename: string | null // null nếu file gốc bị xóa tay (Chroma vẫn là nguồn sự thật)
  totalChunks: number
  sections: string[]
}

// ---- Kết quả phân tích ----
export interface MatchScore {
  overall: number
  skillsMatch: number
  experienceMatch: number
  educationMatch: number
}

export interface SkillMatch {
  skill: string
  presentInCv: boolean
  evidence: string | null // null khi presentInCv=false (luật grounding)
}

export interface ResourceLink {
  title: string
  url: string
  kind: ResourceKind
}

export interface ImprovementSuggestion {
  priority: Priority
  title: string
  detail: string
  relatedSkill: string | null
  resources: ResourceLink[] // backend gắn từ catalog — LLM không sinh URL
}

export interface AnalysisResponse {
  cvId: string
  jdTitle: string | null
  verdict: Verdict
  score: MatchScore
  summary: string
  matchedSkills: SkillMatch[]
  missingSkills: string[]
  suggestions: ImprovementSuggestion[]
  analyzedAt: string
}

// ---- Shape lỗi thống nhất của backend (global AppException handler) ----
export interface ErrorResponse {
  errorCode: string // vd 'CV_NOT_FOUND', 'DOCUMENT_PROCESSING_ERROR', 'LLM_RESPONSE_ERROR'
  message: string
  detail: string | null
}
