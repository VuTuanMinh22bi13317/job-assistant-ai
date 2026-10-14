// src/App.tsx — layout 2 cột: trái = quản lý CV + form JD; phải = kết quả.
// App giữ TOÀN BỘ state gọi API (danh sách, phân tích) — component con chỉ
// thu thập input và bắn callback; cây còn nhỏ, chưa cần Context/store.
import { useCallback, useEffect, useState } from 'react'
import { analyze, ApiError, listCVs } from './api'
import CVList from './components/CVList'
import JDForm from './components/JDForm'
import UploadCV from './components/UploadCV'
import type { AnalysisResponse, CVListItem, Verdict } from './types'

// Nhãn tiếng Việt + màu cho verdict — dùng cho teaser (bước 4) và trang
// kết quả đầy đủ (bước 5).
const VERDICT_HIEN_THI: Record<Verdict, { nhan: string; mau: string }> = {
  strong_match: { nhan: 'Rất phù hợp', mau: 'bg-green-100 text-green-800' },
  good_match: { nhan: 'Khá phù hợp', mau: 'bg-emerald-100 text-emerald-800' },
  partial_match: { nhan: 'Phù hợp một phần', mau: 'bg-yellow-100 text-yellow-800' },
  weak_match: { nhan: 'Còn yếu', mau: 'bg-orange-100 text-orange-800' },
  not_a_match: { nhan: 'Không phù hợp', mau: 'bg-red-100 text-red-800' },
}

function App() {
  const [dsCV, setDsCV] = useState<CVListItem[]>([])
  const [cvDangChon, setCvDangChon] = useState<string | null>(null)
  const [loiTaiDs, setLoiTaiDs] = useState<string | null>(null)

  const [ketQua, setKetQua] = useState<AnalysisResponse | null>(null)
  const [dangPhanTich, setDangPhanTich] = useState(false)
  const [loiPhanTich, setLoiPhanTich] = useState<string | null>(null)

  const taiDanhSach = useCallback(async () => {
    setLoiTaiDs(null)
    try {
      setDsCV(await listCVs())
    } catch (e) {
      setLoiTaiDs(e instanceof ApiError ? e.message : 'Không tải được danh sách CV')
    }
  }, [])

  useEffect(() => {
    void taiDanhSach()
  }, [taiDanhSach])

  async function phanTich(jdContent: string, jdTitle?: string) {
    if (!cvDangChon) return
    setDangPhanTich(true)
    setLoiPhanTich(null)
    setKetQua(null) // xóa kết quả cũ ngay — không để người dùng đọc nhầm báo cáo cũ trong lúc chờ
    try {
      setKetQua(await analyze(cvDangChon, jdContent, jdTitle))
    } catch (e) {
      if (e instanceof ApiError) {
        // Switch theo errorCode — thành quả của ErrorResponse thống nhất backend:
        // mỗi mã lỗi một thông điệp HÀNH ĐỘNG ĐƯỢC, không chỉ "đã có lỗi xảy ra".
        if (e.errorCode === 'CV_NOT_FOUND') {
          setLoiPhanTich('CV này không còn trong hệ thống — danh sách vừa được tải lại, hãy chọn hoặc upload CV khác.')
          setCvDangChon(null)
          void taiDanhSach()
        } else if (e.errorCode === 'LLM_RESPONSE_ERROR') {
          setLoiPhanTich('AI trả kết quả không hợp lệ (trục trặc tạm thời phía Gemini) — bấm Phân tích để thử lại.')
        } else {
          setLoiPhanTich(e.message)
        }
      } else {
        setLoiPhanTich('Lỗi không xác định khi phân tích')
      }
    } finally {
      setDangPhanTich(false)
    }
  }

  const cvChon = dsCV.find((c) => c.cvId === cvDangChon) ?? null

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="border-b bg-white px-6 py-4 shadow-sm">
        <h1 className="text-xl font-bold">
          Job Assistant <span className="text-blue-600">AI</span>
        </h1>
        <p className="text-sm text-slate-500">
          Phân tích CV với Job Description — chấm điểm, bằng chứng, gợi ý cải thiện
        </p>
      </header>

      <main className="mx-auto grid max-w-6xl gap-6 p-6 lg:grid-cols-[380px_1fr]">
        {/* ===== Cột trái ===== */}
        <div className="space-y-4">
          <section>
            <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
              1 · Tải CV lên
            </h2>
            <UploadCV
              onUploaded={(cv) => {
                void taiDanhSach()
                setCvDangChon(cv.cvId)
                setKetQua(null)
              }}
            />
          </section>

          <section>
            <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
              2 · Chọn CV để phân tích
            </h2>
            {loiTaiDs ? (
              <div className="rounded-lg bg-amber-50 px-3 py-3 text-sm text-amber-800">
                ⚠️ {loiTaiDs}
                <button
                  onClick={() => void taiDanhSach()}
                  className="ml-2 font-medium underline hover:no-underline"
                >
                  Thử lại
                </button>
              </div>
            ) : (
              <CVList
                items={dsCV}
                selectedId={cvDangChon}
                onSelect={(cvId) => {
                  setCvDangChon(cvId)
                  setKetQua(null) // đổi CV thì kết quả cũ hết liên quan — dọn ngay
                }}
                onDeleted={(cvId) => {
                  if (cvDangChon === cvId) {
                    setCvDangChon(null)
                    setKetQua(null)
                  }
                  void taiDanhSach()
                }}
              />
            )}
          </section>

          <section>
            <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
              3 · Dán Job Description
            </h2>
            <JDForm daChonCV={cvDangChon !== null} dangChay={dangPhanTich} onPhanTich={phanTich} />
          </section>
        </div>

        {/* ===== Cột phải: 4 trạng thái — chờ / đang chạy / lỗi / kết quả ===== */}
        <div>
          {dangPhanTich ? (
            <div className="rounded-xl border border-blue-200 bg-blue-50 p-10 text-center">
              <div className="mx-auto h-8 w-8 animate-spin rounded-full border-4 border-blue-200 border-t-blue-600" />
              <p className="mt-4 font-medium text-blue-700">Gemini đang phân tích…</p>
              <p className="mt-1 text-sm text-blue-500">
                Truy xuất chunk liên quan → chấm điểm theo rubric → thường mất 5-15 giây.
              </p>
            </div>
          ) : loiPhanTich ? (
            <div className="rounded-xl border border-red-200 bg-red-50 p-8 text-center">
              <p className="font-medium text-red-700">⚠️ {loiPhanTich}</p>
            </div>
          ) : ketQua ? (
            <div className="rounded-xl border bg-white p-6 shadow-sm">
              {/* Teaser bước 4 — bước 5 sẽ thay bằng trang báo cáo đầy đủ */}
              <div className="flex items-center justify-between gap-4">
                <div>
                  <p className="text-sm text-slate-500">{ketQua.jdTitle ?? 'Kết quả phân tích'}</p>
                  <span
                    className={`mt-1 inline-block rounded-full px-3 py-1 text-sm font-semibold ${VERDICT_HIEN_THI[ketQua.verdict].mau}`}
                  >
                    {VERDICT_HIEN_THI[ketQua.verdict].nhan}
                  </span>
                </div>
                <div className="text-right">
                  <p className="text-4xl font-bold text-blue-600">{ketQua.score.overall}</p>
                  <p className="text-xs text-slate-500">/ 100 điểm</p>
                </div>
              </div>
              <p className="mt-4 border-t pt-4 text-sm leading-relaxed text-slate-700">
                {ketQua.summary}
              </p>
              <p className="mt-4 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-400">
                Bước 5/5 sẽ hiển thị đầy đủ: điểm 4 trục, skills + bằng chứng, gợi ý + link học.
              </p>
            </div>
          ) : (
            <div className="rounded-xl border border-dashed border-slate-300 bg-white p-10 text-center">
              <p className="text-lg font-medium">
                {cvChon ? `✅ Đã chọn: ${cvChon.filename ?? cvChon.cvId}` : '🔍 Sẵn sàng phân tích'}
              </p>
              <p className="mt-2 text-sm text-slate-500">
                {cvChon
                  ? 'Dán JD vào ô bên trái rồi bấm Phân tích.'
                  : 'Tải CV lên hoặc chọn một CV, sau đó dán JD.'}
              </p>
            </div>
          )}
        </div>
      </main>
    </div>
  )
}

export default App
