//! Tauri v2 desktop shell for Property Management LeadGen.
//!
//! Launches the Python sidecar as a managed child process on app startup
//! and bridges IPC messages between the frontend webview and the sidecar's
//! stdin/stdout JSON protocol.
//!
//! Communication model:
//!   1. The sidecar is spawned once in `setup()` and kept alive.
//!   2. Each frontend IPC command writes a JSON line to the sidecar's stdin.
//!   3. The Rust layer reads JSON lines from the sidecar's stdout, matching
//!      responses by request-id.  Unsolicited event lines (e.g. captcha
//!      detection) are buffered and exposed via `sidecar_poll_events`.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde_json::Value;
use std::sync::Mutex;
use tauri::{AppHandle, Emitter, Manager, RunEvent, State};
use tauri_plugin_shell::process::CommandEvent;
use tauri_plugin_shell::ShellExt;

// ── Application state ───────────────────────────────────────────────

/// Handle to the running sidecar process and its stdout receiver.
struct SidecarHandle {
    child: tauri_plugin_shell::process::CommandChild,
    rx: tauri_plugin_shell::process::CommandEventReceiver,
}

/// Shared application state managed by Tauri.
struct SidecarState {
    /// The persistent sidecar process handle + stdout receiver.
    /// `None` if the sidecar has not been started or has exited.
    inner: Mutex<Option<SidecarHandle>>,
    /// Buffer for unsolicited events emitted by the sidecar
    /// (e.g. captcha_detected) that the frontend can poll.
    pending_events: Mutex<Vec<Value>>,
}

// ── IPC commands ────────────────────────────────────────────────────

/// Forward a JSON-RPC command from the frontend to the Python sidecar.
///
/// The frontend calls `invoke("sidecar_command", { cmd: { method, params } })`.
/// This handler writes the JSON command to the persistent sidecar's stdin,
/// reads one JSON response line from its stdout, and returns the result.
#[tauri::command]
async fn sidecar_command(
    app: AppHandle,
    cmd: Value,
) -> Result<Value, String> {
    let state = app.state::<SidecarState>();

    // ── Built-in commands handled at the Rust layer ─────────────────
    // These are never forwarded to the Python sidecar.

    let method = cmd.get("method").and_then(|v| v.as_str());

    // sidecar.poll_events — return buffered unsolicited events
    // (captcha detection, etc.) without talking to the sidecar.
    if method == Some("sidecar.poll_events") {
        let events = {
            let mut guard = state
                .pending_events
                .lock()
                .map_err(|e| e.to_string())?;
            std::mem::take(&mut *guard)
        };
        return Ok(serde_json::json!(events));
    }

    // Take exclusive ownership of the sidecar handle so we can read
    // the stdout receiver without racing a background task.
    // MUST return the handle to state in all code paths (success, error, panic).
    let mut handle = {
        let mut guard = state.inner.lock().map_err(|e| e.to_string())?;
        guard.take().ok_or_else(|| "Sidecar is not running".to_string())?
    };

    let result: Result<Value, String> = (|| {
        // Serialise the command as a JSON line for the sidecar's stdin.
        let input = serde_json::to_string(&cmd).map_err(|e| e.to_string())?;

        // Write the JSON command followed by a newline
        handle
            .child
            .write(input.as_bytes())
            .map_err(|e| format!("Failed to write to sidecar stdin: {e}"))?;
        handle
            .child
            .write(b"\n")
            .map_err(|e| format!("Failed to write newline to sidecar stdin: {e}"))?;

        // Read stdout lines until we find a JSON response
        let response: Value = loop {
            match handle.rx.recv().await {
                Some(CommandEvent::Stdout(line)) => {
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
                    eprintln!("[sidecar:err] {}", line);
                }
                Some(CommandEvent::Terminated(payload)) => {
                    eprintln!("[sidecar] Process exited unexpectedly: {:?}", payload);
                    return Err(format!(
                        "Sidecar terminated (code {:?})",
                        payload.code,
                    ));
                }
                None => {
                    return Err("Sidecar stdout channel closed".to_string());
                }
                _ => {}
            }
        };

        // Check for error response
        if let Some(err_obj) = response.get("error") {
            let msg = err_obj
                .get("message")
                .and_then(|v| v.as_str())
                .unwrap_or("Unknown error");
            return Err(msg.to_string());
        }

        Ok(response
            .get("result")
            .cloned()
            .unwrap_or(response))
    })();

    // CRITICAL: Always return the handle to shared state, even on error.
    // If we don't, every future command will get "Sidecar is not running".
    {
        let mut guard = state.inner.lock().map_err(|e| e.to_string())?;
        *guard = Some(handle);
    }

    result
}

/// Return any unsolicited events buffered since the last poll.
///
/// The frontend calls this on a timer (every few seconds) so it can
/// react to sidecar-originated events such as CAPTCHA detection without
/// needing a persistent WebSocket or event-stream connection.
#[tauri::command]
fn sidecar_poll_events(state: State<'_, SidecarState>) -> Vec<Value> {
    let mut guard = match state.pending_events.lock() {
        Ok(g) => g,
        Err(_) => return vec![],
    };
    let events = std::mem::take(&mut *guard);
    events
}

/// Health check — returns `true` if the sidecar process handle is present.
#[tauri::command]
fn sidecar_health(state: State<'_, SidecarState>) -> bool {
    match state.inner.lock() {
        Ok(guard) => guard.is_some(),
        Err(_) => false,
    }
}

// ── Application entry point ─────────────────────────────────────────

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(SidecarState {
            inner: Mutex::new(None),
            pending_events: Mutex::new(Vec::new()),
        })
        .setup(|app| {
            let shell = app.shell();

            let (rx, child) = shell
                .sidecar("python-sidecar")
                .expect("Failed to create sidecar command")
                .spawn()
                .expect("Failed to spawn Python sidecar");

            // Store the persistent sidecar handle in application state.
            let state = app.state::<SidecarState>();
            {
                let mut guard = state.inner.lock().unwrap();
                *guard = Some(SidecarHandle { child, rx });
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
                // Sidecar cleanup is handled by Tauri's lifecycle —
                // the child process is killed when the app exits.
            }
        });
}
