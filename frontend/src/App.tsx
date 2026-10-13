// src/App.tsx — layout 2 cột: trái = quản lý CV (bước 3) + form JD (bước 4);
// phải = kết quả phân tích (bước 5). App giữ state trung tâm, component con
// nhận props — cây còn nhỏ, chưa cần Context/store.
import { useCallback, useEffect, useState } from 'react'
import { ApiError, listCVs } from './api'
import CVList from './components/CVList'
import UploadCV from './components/UploadCV'
import type { CVListItem } from './types'

function App() {
  const [dsCV, setDsCV] = useState<CVListItem[]>([])
  const [cvDangChon, setCvDangChon] = useState<string | null>(null)
  const [loiTaiDs, setLoiTaiDs] = useState<string | null>(null)

  // Tải danh sách từ backend — nguồn sự thật là metadata Chroma (GET /cv).
  const taiDanhSach = useCallback(async () => {
    setLoiTaiDs(null)
    try {
      setDsCV(await listCVs())
    } catch (e) {
      // status 0 = backend chưa bật — thông điệp hành động được, không chỉ "lỗi".
      setLoiTaiDs(e instanceof ApiError ? e.message : 'Không tải được danh sách CV')
    }
  }, [])

  useEffect(() => {
    void taiDanhSach()
  }, [taiDanhSach])

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
        {/* ===== Cột trái: quản lý CV ===== */}
        <div className="space-y-4">
          <section>
            <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
              1 · Tải CV lên
            </h2>
            <UploadCV
              onUploaded={(cv) => {
                // Upload xong: tải lại danh sách từ server (nguồn sự thật)
                // và tự chọn luôn CV mới cho đỡ một cú click.
                void taiDanhSach()
                setCvDangChon(cv.cvId)
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
                onSelect={setCvDangChon}
                onDeleted={(cvId) => {
                  if (cvDangChon === cvId) setCvDangChon(null)
                  void taiDanhSach()
                }}
              />
            )}
          </section>
        </div>

        {/* ===== Cột phải: kết quả (bước 4-5 sẽ thế chỗ) ===== */}
        <div className="rounded-xl border border-dashed border-slate-300 bg-white p-10 text-center">
          {cvChon ? (
            <>
              <p className="text-lg font-medium">
                ✅ Đã chọn: <span className="text-blue-600">{cvChon.filename ?? cvChon.cvId}</span>
              </p>
              <p className="mt-2 text-sm text-slate-500">
                Bước kế (4/5): ô dán JD + nút Phân tích sẽ xuất hiện ở đây.
              </p>
            </>
          ) : (
            <>
              <p className="text-lg font-medium">🏗️ Bước 3/5 — quản lý CV</p>
              <p className="mt-2 text-sm text-slate-500">
                Tải CV lên hoặc chọn một CV bên trái để tiếp tục.
              </p>
            </>
          )}
        </div>
      </main>
    </div>
  )
}

export default App
