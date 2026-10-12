// src/App.tsx — khung trang (bước 1: scaffold). Nội dung thật vào ở bước 3-5.
function App() {
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

      <main className="mx-auto max-w-5xl p-6">
        <div className="rounded-xl border border-dashed border-slate-300 bg-white p-10 text-center">
          <p className="text-lg font-medium">🏗️ Scaffold hoàn tất (bước 1/5)</p>
          <p className="mt-2 text-sm text-slate-500">
            Vite + React 19 + TypeScript + Tailwind v4 — proxy /api → FastAPI :8000.
            <br />
            Bước kế: lớp api.ts + types.ts khớp hợp đồng camelCase của backend.
          </p>
        </div>
      </main>
    </div>
  )
}

export default App
