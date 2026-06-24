//! Tauri v2 desktop shell for Property Management LeadGen.
//!
//! Launches the Python sidecar as a managed child process on app startup
//! and bridges IPC messages between the frontend webview and the sidecar's
//! stdin/stdout JSON protocol.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde_json::Value;
use std::sync::Mutex;
use std::time::Instant;
use tauri::{AppHandle, Manager, RunEvent, State};
use tauri_plugin_shell::process::CommandEvent;
use tauri_plugin_shell::ShellExt;
use tokio::sync::mpsc::Receiver;

const MAX_SIDECAR_RESTARTS: u32 = 3;
const RESTART_WINDOW_SECS: u64 = 60;

struct SidecarHandle {
    child: tauri_plugin_shell::process::CommandChild,
    rx: Receiver<CommandEvent>,
}

struct SidecarState {
    inner: Mutex<Option<SidecarHandle>>,
    pending_events: Mutex<Vec<Value>>,
    restart_count: Mutex<u32>,
    restart_window_start: Mutex<Instant>,
}

fn spawn_sidecar(app: &AppHandle) -> Result<SidecarHandle, String> {
    let shell = app.shell();
    let (rx, child) = shell
        .sidecar("python-sidecar")
        .map_err(|e| format!("Failed to create sidecar command: {e}"))?
        .spawn()
        .map_err(|e| format!("Failed to spawn Python sidecar: {e}"))?;
    Ok(SidecarHandle { child, rx })
}

fn attempt_restart(app: &AppHandle, state: &SidecarState) -> Result<(), String> {
    let now = Instant::now();
    let mut window_start = state.restart_window_start.lock().map_err(|e| e.to_string())?;
    let mut count = state.restart_count.lock().map_err(|e| e.to_string())?;

    if now.duration_since(*window_start).as_secs() > RESTART_WINDOW_SECS {
        *window_start = now;
        *count = 0;
    }

    *count += 1;
    if *count > MAX_SIDECAR_RESTARTS {
        return Err(format!(
            "Sidecar crashed {count} times in {RESTART_WINDOW_SECS}s — giving up",
        ));
    }

    eprintln!("[sidecar] Restarting (attempt {count}/{MAX_SIDECAR_RESTARTS}) ...");
    let new_handle = spawn_sidecar(app)?;
    let mut guard = state.inner.lock().map_err(|e| e.to_string())?;
    *guard = Some(new_handle);
    eprintln!("[sidecar] Restart succeeded");
    Ok(())
}

#[tauri::command]
async fn sidecar_command(
    app: AppHandle,
    cmd: Value,
) -> Result<Value, String> {
    let state = app.state::<SidecarState>();
    let method = cmd.get("method").and_then(|v| v.as_str());

    // sidecar.poll_events — return buffered events without talking to sidecar
    if method == Some("sidecar.poll_events") {
        let events = {
            let mut guard = state.pending_events.lock().map_err(|e| e.to_string())?;
            std::mem::take(&mut *guard)
        };
        return Ok(serde_json::json!(events));
    }

    // Take exclusive ownership of the sidecar handle
    let mut handle = {
        let mut guard = state.inner.lock().map_err(|e| e.to_string())?;
        guard.take().ok_or_else(|| "Sidecar is not running".to_string())?
    };

    // The I/O closure returns Result, handle restoration happens after
    let result: Result<Value, String> = (async {
        let input = serde_json::to_string(&cmd).map_err(|e| e.to_string())?;

        handle
            .child
            .write(input.as_bytes())
            .map_err(|e| format!("Failed to write to sidecar stdin: {e}"))?;
        handle
            .child
            .write(b"\n")
            .map_err(|e| format!("Failed to write newline to sidecar stdin: {e}"))?;

        let response: Value = loop {
            match handle.rx.recv().await {
                Some(CommandEvent::Stdout(line)) => {
                    let line = String::from_utf8_lossy(&line).to_string();
                    if let Ok(value) = serde_json::from_str::<Value>(&line) {
                        if value.get("event").is_some() {
                            let mut events = state
                                .pending_events
                                .lock()
                                .map_err(|e| e.to_string())?;
                            events.push(value);
                            continue;
                        }
                        if value.get("jsonrpc").is_some() || value.get("result").is_some() {
                            break value;
                        }
                        if value.is_object() {
                            break value;
                        }
                    }
                    eprintln!("[sidecar:stdout] (non-JSON) {}", line);
                }
                Some(CommandEvent::Stderr(line)) => {
                    let line = String::from_utf8_lossy(&line);
                    eprintln!("[sidecar:err] {}", line);
                }
                Some(CommandEvent::Terminated(payload)) => {
                    eprintln!("[sidecar] Process exited: {:?}", payload);
                    return Err(format!("Sidecar terminated (code {:?})", payload.code));
                }
                Some(CommandEvent::Error(err)) => {
                    eprintln!("[sidecar] Error: {}", err);
                }
                None => {
                    eprintln!("[sidecar] Channel closed");
                    return Err("Sidecar stdout channel closed".to_string());
                }
                Some(_) => {}  // Ignore other CommandEvent variants
            }
        };

        if let Some(err_obj) = response.get("error") {
            let msg = err_obj
                .get("message")
                .and_then(|v| v.as_str())
                .unwrap_or("Unknown error");
            return Err(msg.to_string());
        }

        Ok(response.get("result").cloned().unwrap_or(response))
    })
    .await;

    // Handle lifecycle: restart on termination, return handle otherwise
    if result
        .as_ref()
        .is_err_and(|e| e.starts_with("Sidecar terminated"))
    {
        drop(handle);
        if let Err(restart_err) = attempt_restart(&app, &state) {
            eprintln!("[sidecar] Restart failed: {restart_err}");
        }
    } else {
        let mut guard = state.inner.lock().map_err(|e| e.to_string())?;
        *guard = Some(handle);
    }

    result
}

#[tauri::command]
fn sidecar_poll_events(state: State<'_, SidecarState>) -> Vec<Value> {
    let mut guard = match state.pending_events.lock() {
        Ok(g) => g,
        Err(_) => return vec![],
    };
    std::mem::take(&mut *guard)
}

#[tauri::command]
fn sidecar_health(state: State<'_, SidecarState>) -> bool {
    match state.inner.lock() {
        Ok(guard) => guard.is_some(),
        Err(_) => false,
    }
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(SidecarState {
            inner: Mutex::new(None),
            pending_events: Mutex::new(Vec::new()),
            restart_count: Mutex::new(0),
            restart_window_start: Mutex::new(Instant::now()),
        })
        .setup(|app| {
            let app_handle = app.handle().clone();
            let handle = spawn_sidecar(&app_handle)
                .expect("Failed to spawn Python sidecar on startup");

            let state = app.state::<SidecarState>();
            {
                let mut guard = state.inner.lock().unwrap();
                *guard = Some(handle);
            }

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            sidecar_command,
            sidecar_poll_events,
            sidecar_health,
        ])
        .build(tauri::generate_context!())
        .expect("Failed to build Tauri application")
        .run(|_app_handle, event| {
            if let RunEvent::ExitRequested { .. } = event {
                // Sidecar cleanup handled by Tauri lifecycle
            }
        });
}
