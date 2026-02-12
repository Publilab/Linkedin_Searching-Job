#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde::Serialize;
use std::env;
use std::fs::{self, OpenOptions};
use std::net::TcpListener;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;
use tauri::{AppHandle, Manager, RunEvent, State};

#[derive(Clone)]
struct AppState {
    api_base: String,
    data_dir: PathBuf,
    logs_dir: PathBuf,
    child: Arc<Mutex<Option<Child>>>,
}

#[derive(Serialize)]
struct AppPaths {
    data_dir: String,
    logs_dir: String,
}

#[derive(Clone)]
struct BackendCommand {
    program: PathBuf,
    args: Vec<String>,
}

const BACKEND_BIN_NAME: &str = "seekjob-backend";

#[tauri::command]
fn get_api_base(state: State<'_, AppState>) -> String {
    state.api_base.clone()
}

#[tauri::command]
fn get_app_paths(state: State<'_, AppState>) -> AppPaths {
    AppPaths {
        data_dir: state.data_dir.to_string_lossy().to_string(),
        logs_dir: state.logs_dir.to_string_lossy().to_string(),
    }
}

#[tauri::command]
fn open_in_chrome(url: String) -> Result<(), String> {
    let chrome_status = Command::new("open")
        .args(["-a", "Google Chrome", &url])
        .status()
        .map_err(|e| format!("Failed to execute 'open -a Google Chrome': {e}"))?;

    if chrome_status.success() {
        return Ok(());
    }

    let fallback_status = Command::new("open")
        .arg(&url)
        .status()
        .map_err(|e| format!("Failed to open URL with default browser: {e}"))?;

    if fallback_status.success() {
        return Ok(());
    }

    Err("Could not open URL in Chrome or fallback browser".to_string())
}

fn reserve_port() -> Result<u16, String> {
    let listener = TcpListener::bind("127.0.0.1:0").map_err(|e| format!("Cannot reserve local port: {e}"))?;
    let port = listener
        .local_addr()
        .map_err(|e| format!("Cannot read reserved port: {e}"))?
        .port();
    drop(listener);
    Ok(port)
}

fn resolve_backend_command(app: &AppHandle) -> Result<BackendCommand, String> {
    if let Ok(path) = std::env::var("SEEKJOB_BACKEND_BIN") {
        let candidate = PathBuf::from(path);
        if candidate.exists() {
            return Ok(BackendCommand {
                program: candidate,
                args: Vec::new(),
            });
        }
    }

    if cfg!(debug_assertions) {
        if let (Ok(py), Ok(script)) = (
            std::env::var("SEEKJOB_BACKEND_DEV_PYTHON"),
            std::env::var("SEEKJOB_BACKEND_DEV_SCRIPT"),
        ) {
            let python = PathBuf::from(py);
            let entry = PathBuf::from(script);
            if python.exists() && entry.exists() {
                return Ok(BackendCommand {
                    program: python,
                    args: vec![entry.to_string_lossy().to_string()],
                });
            }
        }
    }

    let resource_dir = app
        .path()
        .resource_dir()
        .map_err(|e| format!("Cannot resolve Tauri resources dir: {e}"))?;

    let candidates = vec![
        resource_dir.join(BACKEND_BIN_NAME),
        resource_dir.join(format!("backend/dist/{BACKEND_BIN_NAME}")),
        resource_dir.join(format!("backend/{BACKEND_BIN_NAME}")),
        resource_dir.join(format!("_up_/backend/dist/{BACKEND_BIN_NAME}")),
        resource_dir.join(format!("_up_/_up_/backend/dist/{BACKEND_BIN_NAME}")),
    ];

    for candidate in candidates {
        if candidate.exists() {
            return Ok(BackendCommand {
                program: candidate,
                args: Vec::new(),
            });
        }
    }

    if let Some(found) = find_backend_recursive(&resource_dir, 6) {
        return Ok(BackendCommand {
            program: found,
            args: Vec::new(),
        });
    }

    Err(format!(
        "Embedded backend binary not found under {}. Expected file name: {}",
        resource_dir.display(),
        BACKEND_BIN_NAME
    ))
}

fn find_backend_recursive(dir: &Path, max_depth: usize) -> Option<PathBuf> {
    fn walk(dir: &Path, depth: usize, max_depth: usize) -> Option<PathBuf> {
        let entries = fs::read_dir(dir).ok()?;
        let paths: Vec<PathBuf> = entries.filter_map(|entry| entry.ok().map(|e| e.path())).collect();

        for path in &paths {
            if path.is_file()
                && path
                    .file_name()
                    .and_then(|name| name.to_str())
                    .is_some_and(|name| name == BACKEND_BIN_NAME)
            {
                return Some(path.clone());
            }
        }

        if depth >= max_depth {
            return None;
        }

        for path in paths {
            if path.is_dir() {
                if let Some(found) = walk(&path, depth + 1, max_depth) {
                    return Some(found);
                }
            }
        }

        None
    }

    walk(dir, 0, max_depth)
}

fn wait_for_health(api_base: &str, max_wait: Duration) -> bool {
    let mut elapsed = Duration::from_millis(0);
    let step = Duration::from_millis(300);

    while elapsed < max_wait {
        let url = format!("{api_base}/health");
        if let Ok(resp) = ureq::get(&url).call() {
            if resp.status() == 200 {
                return true;
            }
        }

        thread::sleep(step);
        elapsed += step;
    }

    false
}

fn resolve_seekjob_data_dir(app: &AppHandle) -> Result<PathBuf, String> {
    if let Ok(raw) = env::var("SEEKJOB_DATA_DIR_OVERRIDE") {
        let trimmed = raw.trim();
        if !trimmed.is_empty() {
            return Ok(PathBuf::from(trimmed));
        }
    }

    if let Ok(home) = env::var("HOME") {
        let trimmed = home.trim();
        if !trimmed.is_empty() {
            return Ok(
                PathBuf::from(trimmed)
                    .join("Library")
                    .join("Application Support")
                    .join("SeekJob"),
            );
        }
    }

    app.path()
        .app_data_dir()
        .map_err(|e| format!("Cannot resolve app data dir: {e}"))
}

fn resolve_legacy_db_path() -> String {
    if let Ok(raw) = env::var("SEEKJOB_LEGACY_DB_PATH") {
        let trimmed = raw.trim();
        if !trimmed.is_empty() && Path::new(trimmed).exists() {
            return trimmed.to_string();
        }
    }

    let candidates = [
        "/Volumes/PubliLab-EXHD/Publilab/Projects/PubliLab/GitHub/Linkedin/backend/app.db",
        "/Volumes/PubliLab-EXHD/Publilab/Projects/PubliLab/GitHub/linkedin/backend/app.db",
    ];
    for candidate in candidates {
        if Path::new(candidate).exists() {
            return candidate.to_string();
        }
    }

    String::new()
}

fn start_backend(app: &AppHandle) -> Result<AppState, String> {
    let data_dir = resolve_seekjob_data_dir(app)?;
    fs::create_dir_all(&data_dir).map_err(|e| format!("Cannot create app data dir: {e}"))?;

    let logs_dir = data_dir.join("logs");
    fs::create_dir_all(&logs_dir).map_err(|e| format!("Cannot create logs dir: {e}"))?;

    let port = reserve_port()?;
    let api_base = format!("http://127.0.0.1:{port}/api");
    let db_path = data_dir.join("app.db");
    let db_url = format!("sqlite:///{}", db_path.to_string_lossy());

    let backend = resolve_backend_command(app)?;

    let stdout_log = logs_dir.join("backend.stdout.log");
    let stderr_log = logs_dir.join("backend.stderr.log");
    let stdout_file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(stdout_log)
        .map_err(|e| format!("Cannot open backend stdout log: {e}"))?;
    let stderr_file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(stderr_log)
        .map_err(|e| format!("Cannot open backend stderr log: {e}"))?;

    let legacy_path = resolve_legacy_db_path();

    let mut cmd = Command::new(&backend.program);
    if !backend.args.is_empty() {
        cmd.args(backend.args.clone());
    }

    let mut child = cmd
        .env("SEEKJOB_PORT", port.to_string())
        .env("PORT", port.to_string())
        .env("SEEKJOB_DATA_DIR", data_dir.to_string_lossy().to_string())
        .env("DATABASE_URL", db_url)
        .env("SEEKJOB_LEGACY_DB_PATH", legacy_path)
        .stdout(Stdio::from(stdout_file))
        .stderr(Stdio::from(stderr_file))
        .spawn()
        .map_err(|e| format!("Cannot spawn backend process ({}): {e}", backend.program.display()))?;

    if !wait_for_health(&api_base, Duration::from_secs(70)) {
        let _ = child.kill();
        return Err("Backend process started but /api/health did not become ready in time".to_string());
    }

    Ok(AppState {
        api_base,
        data_dir,
        logs_dir,
        child: Arc::new(Mutex::new(Some(child))),
    })
}

fn stop_backend(state: &AppState) {
    if let Ok(mut guard) = state.child.lock() {
        if let Some(child) = guard.as_mut() {
            let _ = child.kill();
        }
        *guard = None;
    }
}

fn main() {
    tauri::Builder::default()
        .setup(|app| {
            let state = match start_backend(app.handle()) {
                Ok(state) => state,
                Err(e) => {
                    eprintln!("Desktop bootstrap failed: {e}");
                    let data_dir = resolve_seekjob_data_dir(app.handle()).unwrap_or_else(|_| PathBuf::from("."));
                    let logs_dir = data_dir.join("logs");
                    let _ = fs::create_dir_all(&logs_dir);
                    AppState {
                        api_base: "http://127.0.0.1:0/api".to_string(),
                        data_dir,
                        logs_dir,
                        child: Arc::new(Mutex::new(None)),
                    }
                }
            };
            app.manage(state);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![get_api_base, get_app_paths, open_in_chrome])
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            if let RunEvent::Exit = event {
                if let Some(state) = app_handle.try_state::<AppState>() {
                    stop_backend(&state);
                }
            }
        });
}
