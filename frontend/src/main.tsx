import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { initSidecar } from './lib/tauri-init'

function renderApp() {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
}

// In Tauri mode, start the backend sidecar BEFORE rendering the app.
// This ensures window.__SHIPAGENT_PORT__ is set before any API calls.
// If sidecar init fails, render the app anyway — it will show degraded
// state (no backend) rather than a blank white screen.
initSidecar()
  .then(() => renderApp())
  .catch((err) => {
    console.error('Sidecar init failed:', err)
    renderApp()
  })
