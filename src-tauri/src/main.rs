#![cfg_attr(
all(not(debug_assertions), target_os = "windows"),
windows_subsystem = "windows"
)]

use app::config::Config as AppConfig;
use app::get_config;
use app::services::db::DB;
use app::services::openai::generate_tags;

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![greet])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

#[tauri::command]
async fn greet(name: &str) -> Result<String, String> {
    let db = DB::new().await.map_err(|err| err.to_string())?;
    db.init_table().await.map_err(|err| err.to_string())?;

    // Write data example
    let rows_affected = db.execute("INSERT INTO brainspread (name) VALUES ('Howdy partner!')")
        .await.map_err(|err| err.to_string())?;
    println!("{} rows affected", rows_affected);

    // Read data example
    let rows: Vec<(i32, String)> = db.query("SELECT id, name FROM brainspread")
        .await.map_err(|err| err.to_string())?;
    println!("{:?}", rows);

    // Format rows as a string
    let mut formatted_rows = String::new();
    for (id, name) in rows {
        formatted_rows.push_str(&format!("id: {}, name: {}\n", id, name));
    }

    Ok(formatted_rows)
}
