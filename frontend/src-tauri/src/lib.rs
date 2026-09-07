use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};

use tauri::{Manager, State};

struct RuntimeProcess {
    child: Mutex<Option<Child>>,
    resource_dir: Mutex<Option<PathBuf>>,
}

impl RuntimeProcess {
    fn new() -> Self {
        Self {
            child: Mutex::new(None),
            resource_dir: Mutex::new(None),
        }
    }
}

impl Drop for RuntimeProcess {
    fn drop(&mut self) {
        if let Ok(mut guard) = self.child.lock() {
            if let Some(mut child) = guard.take() {
                let _ = child.kill();
                let _ = child.wait();
            }
        }
    }
}

fn find_on_path(name: &str) -> Option<PathBuf> {
    let path = std::env::var_os("PATH")?;
    std::env::split_paths(&path)
        .map(|dir| dir.join(name))
        .find(|candidate| candidate.is_file())
}

fn find_python(resource_dir: &Path, app_data_dir: &Path) -> Option<PathBuf> {
    if let Ok(value) = std::env::var("ATRIN_PYTHON") {
        let candidate = PathBuf::from(value);
        if candidate.is_file() {
            return Some(candidate);
        }
    }

    let managed = if cfg!(target_os = "windows") {
        app_data_dir
            .join("Atrin")
            .join("runtime")
            .join("venv")
            .join("Scripts")
            .join("python.exe")
    } else {
        app_data_dir
            .join("Atrin")
            .join("runtime")
            .join("venv")
            .join("bin")
            .join("python3")
    };
    if managed.is_file() {
        return Some(managed);
    }

    let bundled = if cfg!(target_os = "windows") {
        resource_dir.join("runtime").join("python.exe")
    } else {
        resource_dir.join("runtime").join("bin").join("python3")
    };
    if bundled.is_file() {
        return Some(bundled);
    }

    let candidates = if cfg!(target_os = "windows") {
        vec!["python.exe", "python", "py.exe", "py"]
    } else {
        vec!["python3", "python"]
    };
    candidates.into_iter().find_map(find_on_path)
}

fn runtime_is_listening() -> bool {
    std::net::TcpStream::connect_timeout(
        &"127.0.0.1:8765".parse().expect("static socket address"),
        Duration::from_millis(250),
    )
    .is_ok()
}

fn wait_for_runtime_ready(timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if runtime_is_listening() {
            return true;
        }
        thread::sleep(Duration::from_millis(100));
    }
    runtime_is_listening()
}

#[tauri::command]
fn start_runtime(
    app: tauri::AppHandle,
    state: State<'_, RuntimeProcess>,
) -> Result<String, String> {
    if runtime_is_listening() {
        return Ok("already-running".into());
    }

    {
        let mut guard = state
            .child
            .lock()
            .map_err(|_| "Runtime process lock is poisoned".to_string())?;
        if let Some(child) = guard.as_mut() {
            match child.try_wait() {
                Ok(None) => return Ok("starting".into()),
                Ok(Some(_)) => *guard = None,
                Err(error) => return Err(format!("Failed to inspect runtime process: {error}")),
            }
        }
    }

    let resource_dir = app
        .path()
        .resource_dir()
        .map_err(|error| error.to_string())?;
    let data_dir = app
        .path()
        .app_local_data_dir()
        .map_err(|error| error.to_string())?;
    std::fs::create_dir_all(&data_dir)
        .map_err(|error| format!("Cannot create Atrin data directory: {error}"))?;

    let python = find_python(&resource_dir, &data_dir).ok_or_else(|| {
        "Python runtime was not found. Install Python 3.10+ or run ensure-python-runtime.ps1 once to create the managed Atrin runtime.".to_string()
    })?;

    let db_path = data_dir.join("atrin.db");
    let token_path = data_dir.join("runtime_secret.token");
    let mut command = Command::new(&python);
    command
        .arg("-m")
        .arg("atrin_core.runtime")
        .current_dir(&resource_dir)
        .env("PYTHONPATH", &resource_dir)
        .env("ATRIN_DB_PATH", db_path)
        .env("ATRIN_RUNTIME_TOKEN_PATH", token_path)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());

    if let Some(parent) = python.parent() {
        let existing_path = std::env::var_os("PATH").unwrap_or_default();
        let mut paths = vec![parent.to_path_buf()];
        paths.extend(std::env::split_paths(&existing_path));
        if let Ok(joined) = std::env::join_paths(paths) {
            command.env("PATH", joined);
        }
    }

    let child = command
        .spawn()
        .map_err(|error| format!("Failed to start Atrin runtime: {error}"))?;

    {
        let mut guard = state
            .child
            .lock()
            .map_err(|_| "Runtime process lock is poisoned".to_string())?;
        *guard = Some(child);
    }
    *state
        .resource_dir
        .lock()
        .map_err(|_| "Runtime state lock is poisoned".to_string())? = Some(resource_dir);

    if wait_for_runtime_ready(Duration::from_secs(5)) {
        Ok("started".into())
    } else {
        let mut guard = state
            .child
            .lock()
            .map_err(|_| "Runtime process lock is poisoned".to_string())?;
        if let Some(mut child) = guard.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
        Err("Atrin runtime did not become ready on 127.0.0.1:8765".into())
    }
}

#[tauri::command]
fn runtime_status(state: State<'_, RuntimeProcess>) -> Result<String, String> {
    if runtime_is_listening() {
        return Ok("running".into());
    }
    let mut guard = state
        .child
        .lock()
        .map_err(|_| "Runtime process lock is poisoned".to_string())?;
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
    let mut guard = state
        .child
        .lock()
        .map_err(|_| "Runtime process lock is poisoned".to_string())?;
    if let Some(mut child) = guard.take() {
        child
            .kill()
            .map_err(|error| format!("Failed to stop Atrin runtime: {error}"))?;
        let _ = child.wait();
        return Ok("stopped".into());
    }
    Ok("already-stopped".into())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(RuntimeProcess::new())
        .invoke_handler(tauri::generate_handler![
            start_runtime,
            runtime_status,
            stop_runtime
        ])
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
