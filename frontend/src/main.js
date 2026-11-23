import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import './style.css'
import { connectWS } from './store'
import { startFramePlayback } from './demo'

createApp(App).use(router).mount('#app')

if (import.meta.env.VITE_DEMO === '1') {
  startFramePlayback()   // 演示构建：循环回放录制帧
} else {
  connectWS()            // 正常构建：连接真实后端 WebSocket
}
