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
//!
//! Crash recovery:
//!   If the sidecar process exits unexpectedly while handling a command,
//!   `sidecar_command` detects the Terminated event, discards the dead
//!   handle, and attempts to respawn.  Restarts are rate-limited to 3
//!   attempts within a 60-second sliding window.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde_json::Value;
use std::sync::Mutex;
use std::time::Instant;
use tauri::{AppHandle, Emitter, Manager, RunEvent, State};
use tauri_plugin_shell::process::CommandEvent;
use tauri_plugin_shell::ShellExt;

// ── Crash-recovery constants ─────────────────────────────────────────

/// Maximum number of automatic sidecar restarts within the window.
const MAX_SIDECAR_RESTARTS: u32 = 3;

/// Sliding window (seconds) within which restarts are counted.
const RESTART_WINDOW_SECS: u64 = 60;

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
    /// Number of restart attempts in the current sliding window.
    restart_count: Mutex<u32>,
    /// Start of the current restart-rate-limit window.
    restart_window_start: Mutex<Instant>,
}

// ── Sidecar lifecycle helpers ───────────────────────────────────────

/// Spawn a fresh Python sidecar process and return its handle.
fn spawn_sidecar(app: &AppHandle) -> Result<SidecarHandle, String> {
    let shell = app.shell();
    let (rx, child) = shell
        .sidecar("python-sidecar")
        .map_err(|e| format!("Failed to create sidecar command: {e}"))?
        .spawn()
        .map_err(|e| format!("Failed to spawn Python sidecar: {e}"))?;
    Ok(SidecarHandle { child, rx })
}

/// Attempt to restart the sidecar, subject to a rate limit.
///
/// Returns `Ok(())` if a new process was spawned and installed in state.
/// Returns `Err` if the rate limit was exceeded or spawning failed.
fn attempt_restart(app: &AppHandle, state: &SidecarState) -> Result<(), String> {
    let now = Instant::now();

    let mut window_start = state
        .restart_window_start
        .lock()
        .map_err(|e| e.to_string())?;
    let mut count = state.restart_count.lock().map_err(|e| e.to_string())?;

    // Reset the sliding window if enough time has passed since the first
    // restart in the current window.
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

    eprintln!(
        "[sidecar] Restarting (attempt {count}/{MAX_SIDECAR_RESTARTS}) ..."
    );

    let new_handle = spawn_sidecar(app)?;

    // Install the new handle into shared state so subsequent commands can
    // use it immediately.
    let mut guard = state.inner.lock().map_err(|e| e.to_string())?;
    *guard = Some(new_handle);

    eprintln!("[sidecar] Restart succeeded");
    Ok(())
}

// ── IPC commands ────────────────────────────────────────────────────

/// Forward a JSON-RPC command from the frontend to the Python sidecar.
///
/// The frontend calls `invoke("sidecar_command", { cmd: { method, params } })`.
/// This handler writes the JSON command to the persistent sidecar's stdin,
/// reads one JSON response line from its stdout, and returns the result.
///
/// If the sidecar process dies while waiting for a response the handler
/// automatically attempts to respawn it (subject to a rate limit).
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
    // MUST return the handle to state in all code paths unless the
    // process has terminated (in which case the handle is dead and we
    // attempt a restart instead).
    let mut handle = {
        let mut guard = state.inner.lock().map_err(|e| e.to_string())?;
        guard.take().ok_or_else(|| "Sidecar is not running".to_string())?
    };

    // We wrap the I/O in a closure so the restore-or-restart decision
    // happens *after* the borrow on `handle` is released.
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

    // ── Handle lifecycle ────────────────────────────────────────────
    // If the sidecar terminated we must drop the dead handle and attempt
    // a restart.  Otherwise, return the handle to shared state so future
    // commands can use it.

    if result
        .as_ref()
        .is_err_and(|e| e.starts_with("Sidecar terminated"))
    {
        // The process is gone — discard the old handle.
        drop(handle);

        // Attempt to respawn a fresh sidecar (rate-limited).
        if let Err(restart_err) = attempt_restart(&app, &state) {
            eprintln!("[sidecar] Restart failed: {restart_err}");
        }
    } else {
        // Return the handle to state for the next command.
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
                // Sidecar cleanup is handled by Tauri's lifecycle —
                // the child process is killed when the app exits.
            }
        });
}
