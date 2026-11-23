import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

/* VITE_DEMO=1 时构建 GitHub Pages 静态演示版：
 * - base 指向仓库子路径，资源用相对路径，部署到任意 Pages 路径都能工作
 * - demo/snapshot.json 随 public/ 原样拷入产物 */
const DEMO = process.env.VITE_DEMO === '1'

export default defineConfig({
  base: DEMO ? './' : '/',
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/ws': { target: 'ws://127.0.0.1:8000', ws: true },
    },
  },
})
