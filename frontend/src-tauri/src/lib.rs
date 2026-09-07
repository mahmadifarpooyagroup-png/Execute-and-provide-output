use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::Duration;

use tauri::{Manager, State};

struct RuntimeProcess {
    child: Mutex<Option<Child>>,
    resource_dir: Mutex<Option<PathBuf>>,
}

impl RuntimeProcess {
    fn new() -> Self {
        Self { child: Mutex::new(None), resource_dir: Mutex::new(None) }
    }
}

fn find_python(resource_dir: &Path) -> Option<PathBuf> {
    if let Ok(value) = std::env::var("ATRIN_PYTHON") {
        let candidate = PathBuf::from(value);
        if candidate.exists() {
            return Some(candidate);
        }
    }

    let bundled = if cfg!(target_os = "windows") {
        resource_dir.join("runtime").join("python.exe")
    } else {
        resource_dir.join("runtime").join("bin").join("python3")
    };
    if bundled.exists() {
        return Some(bundled);
    }

    for candidate in if cfg!(target_os = "windows") {
        vec!["python.exe", "python", "py"]
    } else {
        vec!["python3", "python"]
    } {
        if let Ok(path) = which::which(candidate) {
            return Some(path);
        }
    }
    None
}

fn runtime_is_listening() -> bool {
    std::net::TcpStream::connect_timeout(
        &"127.0.0.1:8765".parse().expect("static socket address"),
        Duration::from_millis(250),
    )
    .is_ok()
}

#[tauri::command]
fn start_runtime(app: tauri::AppHandle, state: State<'_, RuntimeProcess>) -> Result<String, String> {
    if runtime_is_listening() {
        return Ok("already-running".into());
    }

    let resource_dir = app.path().resource_dir().map_err(|error| error.to_string())?;
    let python = find_python(&resource_dir).ok_or_else(|| {
        "Python runtime was not found. Install Python 3.12+ or provide ATRIN_PYTHON to the application.".to_string()
    })?;

    let data_dir = app.path().app_local_data_dir().map_err(|error| error.to_string())?;
    std::fs::create_dir_all(&data_dir).map_err(|error| format!("Cannot create Atrin data directory: {error}"))?;
    let db_path = data_dir.join("atrin.db");
    let token_path = data_dir.join("runtime_secret.token");

    let child = Command::new(&python)
        .arg("-m")
        .arg("atrin_core.runtime")
        .current_dir(&resource_dir)
        .env("PYTHONPATH", &resource_dir)
        .env("ATRIN_DB_PATH", db_path)
        .env("ATRIN_RUNTIME_TOKEN_PATH", token_path)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|error| format!("Failed to start Atrin runtime: {error}"))?;

    *state.child.lock().map_err(|_| "Runtime process lock is poisoned".to_string())? = Some(child);
    *state.resource_dir.lock().map_err(|_| "Runtime state lock is poisoned".to_string())? = Some(resource_dir);
    Ok("started".into())
}

#[tauri::command]
fn runtime_status(state: State<'_, RuntimeProcess>) -> Result<String, String> {
    if runtime_is_listening() {
        return Ok("running".into());
    }
    let mut guard = state.child.lock().map_err(|_| "Runtime process lock is poisoned".to_string())?;
    if let Some(child) = guard.as_mut() {
        match child.try_wait() {
            Ok(Some(_)) => {
                *guard = None;
                Ok("stopped".into())
            }
            Ok(None) => Ok("starting".into()),
            Err(error) => Err(format!("Failed to inspect runtime process: {error}")),
        }
    } else {
        Ok("stopped".into())
    }
}

#[tauri::command]
fn stop_runtime(state: State<'_, RuntimeProcess>) -> Result<String, String> {
    let mut guard = state.child.lock().map_err(|_| "Runtime process lock is poisoned".to_string())?;
    if let Some(mut child) = guard.take() {
        child.kill().map_err(|error| format!("Failed to stop Atrin runtime: {error}"))?;
        let _ = child.wait();
        return Ok("stopped".into());
    }
    Ok("already-stopped".into())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(RuntimeProcess::new())
        .invoke_handler(tauri::generate_handler![start_runtime, runtime_status, stop_runtime])
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
