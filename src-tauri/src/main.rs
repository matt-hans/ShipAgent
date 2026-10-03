// ShipAgent Tauri v2 desktop wrapper.
//
// Spawns the shipagent-core Python backend from the bundled resources
// directory using tauri-plugin-shell. tauri-plugin-shell does NOT kill the
// child when the parent goes away, so this file kills the exact owned child
// (the retained `CommandChild`) on normal quit (`RunEvent::Exit`) and on
// SIGTERM. A crash or SIGKILL of the app cannot be intercepted and leaves the
// sidecar running until it is stopped manually. Reads the dynamically assigned
// port from sidecar stdout ("SHIPAGENT_PORT=XXXXX").
//
// IMPORTANT: We use shell.command() with a dynamic resource_dir() path,
// NOT shell.sidecar(). Tauri's sidecar() is for externalBin (single files).
// Our PyInstaller one-folder build produces a directory, so we bundle it
// as a Tauri resource and resolve the executable path at runtime.
//
// The trusted custom-protocol bootstrap invokes `start_sidecar`, then replaces
// itself with the shell served at `http://127.0.0.1:<port>/`. That reload uses
// relative API URLs and receives no remote-origin Tauri capability.

use std::sync::Mutex;
use tauri::{Manager, RunEvent};
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;

/// Maximum time (seconds) to wait for the backend to report its port.
const SIDECAR_TIMEOUT_SECS: u64 = 30;

/// Holds the backend child process handle so it isn't dropped prematurely.
/// Stored in Tauri managed state for explicit lifecycle control.
struct BackendProcess(Mutex<Option<CommandChild>>);

/// Kill the sidecar this app spawned, if any. Only the retained child handle is
/// signalled, never a process found by name or path.
fn kill_backend(app: &tauri::AppHandle) {
    let child = app
        .state::<BackendProcess>()
        .0
        .lock()
        .ok()
        .and_then(|mut guard| guard.take());
    if let Some(child) = child {
        if let Err(e) = child.kill() {
            eprintln!("Failed to stop backend sidecar: {e}");
        }
    }
}

#[tauri::command]
async fn start_sidecar(app: tauri::AppHandle) -> Result<u16, String> {
    // Resolve the absolute path to the executable inside the resource directory.
    // Tauri copies the one-folder build to Resources/backend-dist/ at bundle time.
    let resource_path = app
        .path()
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

    let path_str = resource_path.to_str().ok_or_else(|| {
        format!(
            "Resource path contains invalid UTF-8: {}",
            resource_path.display()
        )
    })?;

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

    let port_result = timeout(Duration::from_secs(SIDECAR_TIMEOUT_SECS), async {
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
    })
    .await;

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
    let context = tauri::generate_context!();
    // The updater plugin requires `plugins.updater` (signing pubkey + endpoints)
    // in tauri.conf.json; registering it without that config aborts startup.
    // Auto-update stays off until a real Ed25519 key is provisioned.
    let updater_configured = context.config().plugins.0.contains_key("updater");

    let mut builder = tauri::Builder::default().plugin(tauri_plugin_shell::init());
    if updater_configured {
        builder = builder.plugin(tauri_plugin_updater::Builder::new().build());
    }
    let app = builder
        .manage(BackendProcess(Mutex::new(None)))
        .invoke_handler(tauri::generate_handler![start_sidecar])
        .setup(|app| {
            // The trusted bootstrap calls `invoke('start_sidecar')` once and
            // navigates to the returned loopback origin.
            #[cfg(not(unix))]
            let _ = app;
            #[cfg(unix)]
            {
                // A bare SIGTERM would end the app without any RunEvent; turn
                // it into a normal exit so the sidecar is cleaned up.
                use tokio::signal::unix::{signal, SignalKind};
                let handle = app.handle().clone();
                tauri::async_runtime::spawn(async move {
                    if let Ok(mut term) = signal(SignalKind::terminate()) {
                        term.recv().await;
                        handle.exit(0);
                    }
                });
            }
            Ok(())
        })
        .build(context)
        .expect("error while building ShipAgent");

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            kill_backend(handle);
        }
    });
}
