// components/KetQuaPhanTich.tsx — trang báo cáo đầy đủ ("mặt tiền" của project):
// verdict + điểm 4 trục + đối chiếu kỹ năng kèm BẰNG CHỨNG + gợi ý kèm LINK HỌC.
// Component thuần hiển thị: nhận AnalysisResponse, không gọi API, không giữ state.
import type { AnalysisResponse, Priority, ResourceKind, Verdict } from '../types'

const VERDICT_HIEN_THI: Record<Verdict, { nhan: string; mau: string }> = {
  strong_match: { nhan: 'Rất phù hợp', mau: 'bg-green-100 text-green-800' },
  good_match: { nhan: 'Khá phù hợp', mau: 'bg-emerald-100 text-emerald-800' },
  partial_match: { nhan: 'Phù hợp một phần', mau: 'bg-yellow-100 text-yellow-800' },
  weak_match: { nhan: 'Còn yếu', mau: 'bg-orange-100 text-orange-800' },
  not_a_match: { nhan: 'Không phù hợp', mau: 'bg-red-100 text-red-800' },
}

const PRIORITY_HIEN_THI: Record<Priority, { nhan: string; mau: string }> = {
  high: { nhan: 'Ưu tiên cao', mau: 'bg-red-100 text-red-700' },
  medium: { nhan: 'Ưu tiên vừa', mau: 'bg-amber-100 text-amber-700' },
  low: { nhan: 'Ưu tiên thấp', mau: 'bg-slate-100 text-slate-600' },
}

const KIND_ICON: Record<ResourceKind, string> = {
  docs: '📘', roadmap: '🗺️', course: '🎓', search: '🔎',
}

// Màu thanh điểm ăn theo ĐÚNG các band của MatchVerdict.from_score ở backend
// (85/70/50/30) — người dùng nhìn màu là đoán được band, một mô hình tư duy
// duy nhất xuyên suốt backend-frontend.
function mauDiem(diem: number): string {
  if (diem >= 85) return 'bg-green-500'
  if (diem >= 70) return 'bg-emerald-500'
  if (diem >= 50) return 'bg-yellow-500'
  if (diem >= 30) return 'bg-orange-500'
  return 'bg-red-500'
}

function ThanhDiem({ nhan, diem }: { nhan: string; diem: number }) {
  return (
    <div>
      <div className="flex justify-between text-xs text-slate-600">
        <span>{nhan}</span>
        <span className="font-semibold">{diem}</span>
      </div>
      <div className="mt-1 h-2 overflow-hidden rounded-full bg-slate-100">
        <div className={`h-full rounded-full ${mauDiem(diem)}`} style={{ width: `${diem}%` }} />
      </div>
    </div>
  )
}

const THU_TU_PRIORITY: Record<Priority, number> = { high: 0, medium: 1, low: 2 }

export default function KetQuaPhanTich({ ketQua }: { ketQua: AnalysisResponse }) {
  const verdict = VERDICT_HIEN_THI[ketQua.verdict]
  // Sort bản sao — không mutate prop (suggestions backend đã trả theo thứ tự
  // LLM sinh, ta muốn high lên đầu bất kể).
  const goiY = [...ketQua.suggestions].sort(
    (a, b) => THU_TU_PRIORITY[a.priority] - THU_TU_PRIORITY[b.priority],
  )

  return (
    <div className="space-y-4">
      {/* ===== Tổng quan: verdict + điểm + summary ===== */}
      <section className="rounded-xl border bg-white p-6 shadow-sm">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-sm text-slate-500">{ketQua.jdTitle ?? 'Kết quả phân tích'}</p>
            <span
              className={`mt-1 inline-block rounded-full px-3 py-1 text-sm font-semibold ${verdict.mau}`}
            >
              {verdict.nhan}
            </span>
          </div>
          <div className="text-right">
            <p className="text-4xl font-bold text-blue-600">{ketQua.score.overall}</p>
            <p className="text-xs text-slate-500">/ 100 điểm</p>
          </div>
        </div>

        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          <ThanhDiem nhan="Kỹ năng" diem={ketQua.score.skillsMatch} />
          <ThanhDiem nhan="Kinh nghiệm" diem={ketQua.score.experienceMatch} />
          <ThanhDiem nhan="Học vấn" diem={ketQua.score.educationMatch} />
        </div>

        <p className="mt-4 border-t pt-4 text-sm leading-relaxed text-slate-700">
          {ketQua.summary}
        </p>
      </section>

      {/* ===== Đối chiếu kỹ năng theo JD (kèm bằng chứng — tính minh bạch) ===== */}
      <section className="rounded-xl border bg-white p-6 shadow-sm">
        <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
          Đối chiếu kỹ năng theo JD
        </h3>
        <ul className="space-y-2.5">
          {ketQua.matchedSkills.map((s) => (
            <li key={s.skill} className="text-sm">
              <div className="flex items-start gap-2">
                <span className={s.presentInCv ? 'text-green-600' : 'text-red-500'}>
                  {s.presentInCv ? '✓' : '✗'}
                </span>
                <span className={s.presentInCv ? 'font-medium' : 'text-slate-500'}>
                  {s.skill}
                </span>
              </div>
              {/* Evidence = trích dẫn từ CV — người dùng TỰ KIỂM CHỨNG được,
                  đúng triết lý grounding của backend */}
              {s.evidence && (
                <p className="ml-6 mt-0.5 border-l-2 border-slate-200 pl-2 text-xs italic text-slate-500">
                  “{s.evidence}”
                </p>
              )}
            </li>
          ))}
        </ul>

        {ketQua.missingSkills.length > 0 && (
          <div className="mt-4 border-t pt-3">
            <p className="mb-2 text-xs font-semibold text-slate-500">Thiếu so với JD:</p>
            <div className="flex flex-wrap gap-1.5">
              {ketQua.missingSkills.map((k) => (
                <span
                  key={k}
                  className="rounded-full bg-red-50 px-2.5 py-1 text-xs text-red-700"
                >
                  {k}
                </span>
              ))}
            </div>
          </div>
        )}
      </section>

      {/* ===== Gợi ý cải thiện + link học (resources từ catalog backend) ===== */}
      <section className="rounded-xl border bg-white p-6 shadow-sm">
        <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
          Gợi ý cải thiện CV
        </h3>
        <div className="space-y-3">
          {goiY.map((g, i) => (
            <div key={i} className="rounded-lg border border-slate-200 p-3">
              <div className="flex items-center gap-2">
                <span
                  className={`rounded px-1.5 py-0.5 text-[11px] font-semibold ${PRIORITY_HIEN_THI[g.priority].mau}`}
                >
                  {PRIORITY_HIEN_THI[g.priority].nhan}
                </span>
                <p className="text-sm font-medium">{g.title}</p>
              </div>
              <p className="mt-1.5 text-sm leading-relaxed text-slate-600">{g.detail}</p>
              {g.resources.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-2">
                  {g.resources.map((r) => (
                    <a
                      key={r.url}
                      href={r.url}
                      target="_blank"
                      rel="noopener noreferrer" // chặn tab mới điều khiển ngược window.opener
                      className="rounded-md bg-blue-50 px-2 py-1 text-xs text-blue-700 hover:bg-blue-100 hover:underline"
                    >
                      {KIND_ICON[r.kind]} {r.title}
                    </a>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </section>

      <p className="text-center text-xs text-slate-400">
        Phân tích lúc {new Date(ketQua.analyzedAt).toLocaleString('vi-VN')} ·
        bằng chứng trích từ CV để bạn tự kiểm chứng — AI có thể sai, hãy đọc lại trước khi tin.
      </p>
    </div>
  )
}
