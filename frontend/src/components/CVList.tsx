// components/CVList.tsx — danh sách CV đã upload: chọn để phân tích, xóa trọn đời.
import { useState } from 'react'
import { ApiError, deleteCV } from '../api'
import type { CVListItem } from '../types'

interface Props {
  items: CVListItem[]
  selectedId: string | null
  onSelect: (cvId: string) => void
  onDeleted: (cvId: string) => void
}

export default function CVList({ items, selectedId, onSelect, onDeleted }: Props) {
  // Xóa 2 bước thay cho window.confirm: bấm "Xóa" -> nút đổi thành "Chắc chắn?"
  // (confirm() chặn cả tab + không style được; pattern này giữ UI mượt và test được).
  const [choXacNhan, setChoXacNhan] = useState<string | null>(null)
  const [dangXoa, setDangXoa] = useState<string | null>(null)
  const [loi, setLoi] = useState<string | null>(null)

  async function xuLyXoa(cvId: string) {
    if (choXacNhan !== cvId) {
      setChoXacNhan(cvId)
      return
    }
    setChoXacNhan(null)
    setDangXoa(cvId)
    setLoi(null)
    try {
      await deleteCV(cvId)
      onDeleted(cvId)
    } catch (e) {
      setLoi(e instanceof ApiError ? e.message : 'Không xóa được CV')
    } finally {
      setDangXoa(null)
    }
  }

  if (items.length === 0) {
    return (
      <p className="rounded-lg bg-slate-100 px-3 py-4 text-center text-sm text-slate-500">
        Chưa có CV nào — tải CV đầu tiên lên ở ô phía trên.
      </p>
    )
  }

  return (
    <div className="space-y-2">
      {loi && (
        <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{loi}</p>
      )}
      {items.map((cv) => (
        <div
          key={cv.cvId}
          onClick={() => onSelect(cv.cvId)}
          className={`cursor-pointer rounded-lg border p-3 transition
            ${selectedId === cv.cvId
              ? 'border-blue-500 bg-blue-50 ring-1 ring-blue-500'
              : 'border-slate-200 bg-white hover:border-blue-300'}`}
        >
          <div className="flex items-center justify-between gap-2">
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">
                {cv.filename ?? <span className="italic text-slate-400">(mất tên file)</span>}
              </p>
              <p className="mt-0.5 text-xs text-slate-500">
                {cv.totalChunks} chunk · {cv.sections.join(', ')}
              </p>
            </div>
            <button
              onClick={(e) => {
                e.stopPropagation() // đừng để click nút Xóa kích hoạt luôn onSelect của card
                void xuLyXoa(cv.cvId)
              }}
              disabled={dangXoa === cv.cvId}
              className={`shrink-0 rounded-md px-2 py-1 text-xs font-medium transition
                ${choXacNhan === cv.cvId
                  ? 'bg-red-600 text-white hover:bg-red-700'
                  : 'bg-slate-100 text-slate-600 hover:bg-red-50 hover:text-red-600'}
                disabled:opacity-50`}
            >
              {dangXoa === cv.cvId ? 'Đang xóa…' : choXacNhan === cv.cvId ? 'Chắc chắn?' : 'Xóa'}
            </button>
          </div>
        </div>
      ))}
    </div>
  )
}
