// components/JDForm.tsx — ô dán Job Description + nút Phân tích.
// Form CHỈ thu thập input; việc gọi API + giữ kết quả do App làm (một chỗ
// duy nhất sở hữu state phân tích — cùng triết lý với CVList/UploadCV).
import { useState } from 'react'

// Phản chiếu ràng buộc min_length=30 của JDInput backend — fail sớm phía UX,
// backend vẫn là người gác thật.
const JD_TOI_THIEU = 30

interface Props {
  daChonCV: boolean
  dangChay: boolean
  onPhanTich: (jdContent: string, jdTitle?: string) => void
}

export default function JDForm({ daChonCV, dangChay, onPhanTich }: Props) {
  const [tieuDe, setTieuDe] = useState('')
  const [noiDung, setNoiDung] = useState('')

  const soKyTu = noiDung.trim().length
  const duDai = soKyTu >= JD_TOI_THIEU
  const sanSang = daChonCV && duDai && !dangChay

  return (
    <div className="space-y-2">
      <input
        type="text"
        value={tieuDe}
        onChange={(e) => setTieuDe(e.target.value)}
        placeholder="Tên vị trí (tùy chọn) — vd: Junior Backend Engineer"
        maxLength={200}
        disabled={dangChay}
        className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm
                   focus:border-blue-500 focus:outline-none disabled:opacity-60"
      />

      {/* textarea = dán JD nhiều dòng thoải mái; JSON.stringify trong api.ts
          tự escape nên không bao giờ dính lỗi control-character như Swagger */}
      <textarea
        value={noiDung}
        onChange={(e) => setNoiDung(e.target.value)}
        placeholder="Dán toàn văn Job Description vào đây..."
        rows={8}
        disabled={dangChay}
        className="w-full resize-y rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm
                   focus:border-blue-500 focus:outline-none disabled:opacity-60"
      />

      <div className="flex items-center justify-between gap-3">
        <p className="text-xs text-slate-500">
          {!daChonCV
            ? 'Chọn một CV ở trên trước đã.'
            : !duDai
              ? `Cần tối thiểu ${JD_TOI_THIEU} ký tự (hiện ${soKyTu}).`
              : `${soKyTu} ký tự — sẵn sàng.`}
        </p>
        <button
          onClick={() => onPhanTich(noiDung.trim(), tieuDe.trim() || undefined)}
          disabled={!sanSang}
          className="shrink-0 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white
                     transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {dangChay ? 'Đang phân tích…' : '🔍 Phân tích'}
        </button>
      </div>
    </div>
  )
}
