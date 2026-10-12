import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Proxy: frontend gọi fetch('/api/...') -> Vite chuyển tiếp sang backend
    // FastAPI (localhost:8000) và BỎ prefix '/api' (backend không có prefix đó).
    // Lợi ích: code frontend không hardcode địa chỉ backend (deploy đổi 1 chỗ),
    // và trong dev thì request cùng origin -> không đụng CORS.
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
