// components/UploadCV.tsx — ô upload CV: click chọn file hoặc kéo-thả.
import { useRef, useState } from 'react'
import { ApiError, uploadCV } from '../api'
import type { CVUploadResponse } from '../types'

// Validate phía client PHẢN CHIẾU luật backend (đuôi + 5MB) — để fail sớm,
// không tốn một round-trip cho lỗi biết trước. Backend vẫn là người gác THẬT
// (không bao giờ tin client); đây chỉ là lớp UX.
const DUOI_CHO_PHEP = ['.pdf', '.txt', '.md']
const MAX_MB = 5

interface Props {
  onUploaded: (cv: CVUploadResponse) => void
}

export default function UploadCV({ onUploaded }: Props) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dangTai, setDangTai] = useState(false)
  const [loi, setLoi] = useState<string | null>(null)
  const [dangKeo, setDangKeo] = useState(false)

  async function xuLyFile(file: File) {
    setLoi(null)

    const duoi = '.' + (file.name.split('.').pop() ?? '').toLowerCase()
    if (!DUOI_CHO_PHEP.includes(duoi)) {
      setLoi(`Định dạng không hỗ trợ — chỉ nhận ${DUOI_CHO_PHEP.join(', ')}`)
      return
    }
    if (file.size > MAX_MB * 1024 * 1024) {
      setLoi(`File quá lớn (tối đa ${MAX_MB}MB)`)
      return
    }

    setDangTai(true)
    try {
      // Chờ parse + embed xong (backend xử lý sync) — thường vài giây.
      onUploaded(await uploadCV(file))
    } catch (e) {
      setLoi(e instanceof ApiError ? e.message : 'Lỗi không xác định khi upload')
    } finally {
      setDangTai(false)
    }
  }

  return (
    <div>
      <div
        onClick={() => !dangTai && inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault() // bắt buộc: không preventDefault thì browser mở file thay vì drop
          setDangKeo(true)
        }}
        onDragLeave={() => setDangKeo(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDangKeo(false)
          const file = e.dataTransfer.files[0]
          if (file && !dangTai) void xuLyFile(file)
        }}
        className={`cursor-pointer rounded-xl border-2 border-dashed p-6 text-center transition
          ${dangKeo ? 'border-blue-500 bg-blue-50' : 'border-slate-300 bg-white hover:border-blue-400'}
          ${dangTai ? 'pointer-events-none opacity-60' : ''}`}
      >
        {dangTai ? (
          <p className="text-sm font-medium text-blue-600">
            ⏳ Đang tải lên &amp; lập chỉ mục (parse → embedding → vector DB)...
          </p>
        ) : (
          <>
            <p className="font-medium">📄 Kéo thả CV vào đây hoặc bấm để chọn</p>
            <p className="mt-1 text-xs text-slate-500">
              {DUOI_CHO_PHEP.join(' / ')} — tối đa {MAX_MB}MB
            </p>
          </>
        )}
      </div>

      {loi && (
        <p className="mt-2 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{loi}</p>
      )}

      <input
        ref={inputRef}
        type="file"
        accept={DUOI_CHO_PHEP.join(',')}
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) void xuLyFile(file)
          e.target.value = '' // reset để chọn lại cùng 1 file vẫn bắn onChange
        }}
      />
    </div>
  )
}
