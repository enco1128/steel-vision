import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import './style.css'
import { connectWS } from './store'

createApp(App).use(router).mount('#app')
connectWS()
