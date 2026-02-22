// ShipAgent Tauri v2 desktop wrapper.
//
// Spawns the shipagent-core Python backend from the bundled resources
// directory using tauri-plugin-shell (auto-kills on parent crash — no
// zombies). Reads the dynamically assigned port from sidecar stdout
// ("SHIPAGENT_PORT=XXXXX").
//
// IMPORTANT: We use shell.command() with a dynamic resource_dir() path,
// NOT shell.sidecar(). Tauri's sidecar() is for externalBin (single files).
// Our PyInstaller one-folder build produces a directory, so we bundle it
// as a Tauri resource and resolve the executable path at runtime.

use std::sync::Mutex;
use tauri::Manager;
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;

/// Maximum time (seconds) to wait for the backend to report its port.
const SIDECAR_TIMEOUT_SECS: u64 = 30;

/// Holds the backend child process handle so it isn't dropped prematurely.
/// Stored in Tauri managed state for explicit lifecycle control.
struct BackendProcess(Mutex<Option<CommandChild>>);

#[tauri::command]
async fn start_sidecar(app: tauri::AppHandle) -> Result<u16, String> {
    // Resolve the absolute path to the executable inside the resource directory.
    // Tauri copies the one-folder build to Resources/backend-dist/ at bundle time.
    let resource_path = app.path()
        .resource_dir()
        .map_err(|e| format!("Failed to resolve resource dir: {e}"))?
        .join("backend-dist")
        .join("shipagent-core");

    if !resource_path.exists() {
        return Err(format!(
            "Backend binary not found at: {}",
            resource_path.display()
        ));
    }

    let path_str = resource_path
        .to_str()
        .ok_or_else(|| format!("Resource path contains invalid UTF-8: {}", resource_path.display()))?;

    let shell = app.shell();

    // Spawn backend — tauri-plugin-shell manages lifecycle automatically.
    // Port 0 tells uvicorn to bind to an OS-assigned port.
    let (mut rx, child) = shell
        .command(path_str)
        .args(["serve", "--port", "0"])
        .spawn()
        .map_err(|e| format!("Failed to spawn backend: {e}"))?;

    // Store child handle in managed state to prevent premature drop.
    let state = app.state::<BackendProcess>();
    *state.0.lock().unwrap() = Some(child);

    // Read stdout line-by-line until we see the port report, with a timeout
    // to prevent hanging forever if the backend crashes during startup.
    use tauri_plugin_shell::process::CommandEvent;
    use tokio::time::{timeout, Duration};

    let port_result = timeout(
        Duration::from_secs(SIDECAR_TIMEOUT_SECS),
        async {
            while let Some(event) = rx.recv().await {
                match event {
                    CommandEvent::Stdout(line) => {
                        let text = String::from_utf8_lossy(&line);
                        // Check for startup failure signal
                        if text.starts_with("SHIPAGENT_ERROR=") {
                            return Err(format!("Backend startup failed: {}", text.trim()));
                        }
                        if let Some(p) = text.strip_prefix("SHIPAGENT_PORT=") {
                            if let Ok(port) = p.trim().parse::<u16>() {
                                return Ok(port);
                            }
                        }
                    }
                    CommandEvent::Error(e) => {
                        // CommandEvent::Error may be stderr lines or I/O errors.
                        // Don't treat as fatal — uvicorn logs go to stderr.
                        eprintln!("Backend process event: {e}");
                    }
                    CommandEvent::Terminated(payload) => {
                        return Err(format!("Backend exited early: {:?}", payload.code));
                    }
                    _ => {}
                }
            }
            Err("Backend stdout closed without reporting a port".to_string())
        }
    ).await;

    match port_result {
        Ok(Ok(port)) => Ok(port),
        Ok(Err(e)) => Err(e),
        Err(_) => Err(format!(
            "Backend did not report a port within {}s. Check logs for startup errors.",
            SIDECAR_TIMEOUT_SECS
        )),
    }
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .manage(BackendProcess(Mutex::new(None)))
        .invoke_handler(tauri::generate_handler![start_sidecar])
        .setup(|_app| {
            // The frontend JS calls `invoke('start_sidecar')` on load and
            // sets `window.__SHIPAGENT_PORT__` with the returned port.
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running ShipAgent");
}
