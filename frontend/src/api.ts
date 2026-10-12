// src/api.ts — lớp gọi backend DUY NHẤT của frontend (fetch thuần, không lib).
//
// Mọi component chỉ import hàm từ đây, không tự fetch — một chỗ duy nhất biết:
// - đường dẫn ('/api' đi qua Vite proxy -> FastAPI :8000),
// - cách gửi (JSON vs multipart — multipart KHÔNG tự set Content-Type!),
// - cách đọc lỗi (3 shape khác nhau của backend -> gom về MỘT class ApiError).
import type {
  AnalysisResponse,
  CVListItem,
  CVUploadResponse,
  ErrorResponse,
} from './types'

const API_BASE = '/api'

// Phân tích mất 5-15s (Gemini suy nghĩ); /direct còn thêm upload + embed.
// Đặt trần 120s: đủ rộng cho LLM, đủ chặt để không treo vô hạn khi mạng chết.
const TIMEOUT_MS = 120_000

/**
 * Một lỗi API duy nhất cho toàn frontend — component chỉ cần switch theo
 * errorCode/status, không bao giờ phải tự parse body lỗi.
 */
export class ApiError extends Error {
  /** HTTP status; 0 = không tới được server (mạng rớt / backend chưa bật) */
  readonly status: number
  /** Mã máy đọc được từ ErrorResponse của backend (vd 'CV_NOT_FOUND'); null nếu lỗi không thuộc shape đó */
  readonly errorCode: string | null

  constructor(message: string, status: number, errorCode: string | null = null) {
    super(message)
    this.status = status
    this.errorCode = errorCode
  }
}

/**
 * Đọc body lỗi và quy về ApiError. Backend có 3 shape lỗi (bài học từ lúc
 * test tay Swagger):
 * 1. ErrorResponse của ta  : {errorCode, message, detail}  — lỗi nghiệp vụ 404/422/502
 * 2. FastAPI validation    : {detail: [{loc, msg, ...}]}   — request sai hình thức
 * 3. Không phải JSON       : HTML/plain khi lỗi hạ tầng bất ngờ
 */
async function toApiError(resp: Response): Promise<ApiError> {
  let body: unknown = null
  try {
    body = await resp.json()
  } catch {
    return new ApiError(`Lỗi ${resp.status} từ server`, resp.status)
  }

  const b = body as Partial<ErrorResponse> & { detail?: unknown }
  if (typeof b.errorCode === 'string' && typeof b.message === 'string') {
    return new ApiError(b.message, resp.status, b.errorCode) // shape 1
  }
  if (Array.isArray(b.detail)) {
    // shape 2: lấy msg đầu tiên cho người đọc, không dump cả mảng kỹ thuật
    const first = b.detail[0] as { msg?: string } | undefined
    return new ApiError(first?.msg ?? 'Dữ liệu gửi lên không hợp lệ', resp.status)
  }
  return new ApiError(`Lỗi ${resp.status} từ server`, resp.status)
}

/** Lõi request dùng chung: timeout, phân loại lỗi, parse JSON (204 -> undefined). */
async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS)

  let resp: Response
  try {
    resp = await fetch(`${API_BASE}${path}`, { ...init, signal: controller.signal })
  } catch (e) {
    // fetch chỉ reject khi KHÔNG tới được server (mạng/backend tắt) hoặc abort
    // — HTTP 4xx/5xx vẫn resolve bình thường, xử ở nhánh dưới.
    const timedOut = e instanceof DOMException && e.name === 'AbortError'
    throw new ApiError(
      timedOut
        ? 'Server phản hồi quá lâu — thử lại sau.'
        : 'Không kết nối được backend — kiểm tra server đã chạy chưa (uvicorn :8000).',
      0,
    )
  } finally {
    clearTimeout(timer)
  }

  if (!resp.ok) throw await toApiError(resp)
  if (resp.status === 204) return undefined as T
  return (await resp.json()) as T
}

// ==========================================================================
// Các hàm public — mỗi endpoint backend một hàm, tên và kiểu khớp hợp đồng
// ==========================================================================

/** GET /cv — danh sách CV đã upload (màn "CV của tôi"). */
export function listCVs(): Promise<CVListItem[]> {
  return request<CVListItem[]>('/cv')
}

/** POST /cv/upload — upload 1 CV (dùng khi muốn 1 CV chạy nhiều JD). */
export function uploadCV(file: File): Promise<CVUploadResponse> {
  const form = new FormData()
  form.append('file', file)
  // CHÚ Ý: không set Content-Type — browser tự thêm multipart boundary.
  // Tự set 'multipart/form-data' thủ công là MẤT boundary -> backend parse fail.
  return request<CVUploadResponse>('/cv/upload', { method: 'POST', body: form })
}

/** DELETE /cv/{cvId} — xóa trọn CV (index Chroma + file gốc). 204 khi xong. */
export function deleteCV(cvId: string): Promise<void> {
  return request<void>(`/cv/${encodeURIComponent(cvId)}`, { method: 'DELETE' })
}

/** POST /analysis — phân tích CV ĐÃ upload với một JD. */
export function analyze(
  cvId: string,
  jdContent: string,
  jdTitle?: string,
): Promise<AnalysisResponse> {
  return request<AnalysisResponse>('/analysis', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    // JSON.stringify tự escape xuống dòng trong JD — chính cái lỗi
    // "Invalid control character" hồi test tay Swagger không thể xảy ra ở đây.
    body: JSON.stringify({ cvId, jd: { title: jdTitle ?? null, content: jdContent } }),
  })
}

/** POST /analysis/direct — upload + phân tích MỘT phát (multipart). */
export function analyzeDirect(
  file: File,
  jdContent: string,
  jdTitle?: string,
): Promise<AnalysisResponse> {
  const form = new FormData()
  form.append('file', file)
  form.append('jdContent', jdContent)
  if (jdTitle) form.append('jdTitle', jdTitle)
  return request<AnalysisResponse>('/analysis/direct', { method: 'POST', body: form })
}
