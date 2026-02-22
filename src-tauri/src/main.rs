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

use tauri::Manager;
use tauri_plugin_shell::ShellExt;

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

    let shell = app.shell();

    // Spawn backend — tauri-plugin-shell manages lifecycle automatically.
    // Port 0 tells uvicorn to bind to an OS-assigned port.
    let (mut rx, _child) = shell
        .command(resource_path.to_str().unwrap())
        .args(["serve", "--port", "0"])
        .spawn()
        .map_err(|e| format!("Failed to spawn backend: {e}"))?;

    // Read stdout line-by-line until we see the port report.
    use tauri_plugin_shell::process::CommandEvent;
    let mut port: Option<u16> = None;

    while let Some(event) = rx.recv().await {
        match event {
            CommandEvent::Stdout(line) => {
                let text = String::from_utf8_lossy(&line);
                if let Some(p) = text.strip_prefix("SHIPAGENT_PORT=") {
                    port = p.trim().parse().ok();
                    break;
                }
            }
            CommandEvent::Error(e) => {
                return Err(format!("Backend stderr: {e}"));
            }
            CommandEvent::Terminated(payload) => {
                return Err(format!("Backend exited early: {:?}", payload.code));
            }
            _ => {}
        }
    }

    port.ok_or_else(|| "Backend did not report a port".to_string())
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .invoke_handler(tauri::generate_handler![start_sidecar])
        .setup(|_app| {
            // The frontend JS calls `invoke('start_sidecar')` on load and
            // sets `window.__SHIPAGENT_PORT__` with the returned port.
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running ShipAgent");
}
