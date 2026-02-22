import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { initSidecar } from './lib/tauri-init'

// In Tauri mode, start the backend sidecar BEFORE rendering the app.
// This ensures window.__SHIPAGENT_PORT__ is set before any API calls.
initSidecar().then(() => {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
})
