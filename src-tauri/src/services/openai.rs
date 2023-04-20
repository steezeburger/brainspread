use color_eyre::eyre::WrapErr;
use reqwest::Client;
use serde::Deserialize;
// use serde_json::Value;

use crate::get_config;

#[derive(Deserialize, Debug)]
struct ApiResponse {
    choices: Option<Vec<Choice>>,
}

#[derive(Default, Debug, Clone, PartialEq, Deserialize)]
struct Choice {
    message: Message,
    index: i64,
    // logprobs: Value,
    finish_reason: String,
}

#[derive(Default, Debug, Clone, PartialEq, Deserialize)]
struct Message {
    role: String,
    content: String,
}


/// Generate a summary of the given text.
pub async fn generate_summary(title: &str, contents: &str) -> color_eyre::Result<String> {
    // FIXME - this is just for poc. we don't want to read file everytime we want to make a request.
    let conf = get_config()?;

    let client = Client::new();

    let api_key = conf.openai_api_key;
    let api_url = "https://api.openai.com/v1/chat/completions";

    // TODO - add options for summary length, complexity, etc.
    let content = format!(
        r#"
        You will be given a title and text.
        Generate a summary of the text.
        The summary should be readable in less than 5 minutes.
        \n\n
        Title: {}\n\n
        Text: {}\n\n
        Summary:
        "#,
        title, contents
    );

    let response = client
        .post(api_url)
        .header("Content-Type", "application/json")
        .header("Authorization", format!("Bearer {}", api_key))
        .json(&serde_json::json!({
            "model": "gpt-4",
            "temperature": 0.5,
            "messages": [{
                "role": "user",
                "content": content,
            }]
        }))
        .send()
        .await
        .wrap_err("failed sending POST request to endpoint")?;
    let response = response
        .error_for_status()
        .wrap_err("server responded with error code")?
        .json::<ApiResponse>()
        .await
        .wrap_err("failed parsing response as JSON")?;

    let summary = response.choices.unwrap()[0]
        .message
        .content
        .trim()
        .to_string();

    Ok(summary)
}

/// Generate labels for a given text.
pub async fn generate_labels(title: &str, contents: &str) -> color_eyre::Result<Vec<String>> {
    // FIXME - this is just for poc. we don't want to read file everytime we want to make a request.
    let conf = get_config()?;

    let client = Client::new();

    let api_key = conf.openai_api_key;
    let api_url = "https://api.openai.com/v1/chat/completions";

    // TODO - add options for summary length, complexity, etc.
    let content = format!(
        r#"
        You will be given a title and text.
        Generate 5 labels that accurately describe the text.
        You will only respond with the labels separated by commas.
        \n\n
        Title: {}\n\n
        Text: {}\n\n
        Summary:
        "#,
        title, contents
    );

    let response = client
        .post(api_url)
        .header("Content-Type", "application/json")
        .header("Authorization", format!("Bearer {}", api_key))
        .json(&serde_json::json!({
            "model": "gpt-4",
            "temperature": 0.5,
            "messages": [{
                "role": "user",
                "content": content,
            }]
        }))
        .send()
        .await
        .wrap_err("failed sending POST request to endpoint")?;
    let response = response
        .error_for_status()
        .wrap_err("server responded with error code")?
        .json::<ApiResponse>()
        .await
        .wrap_err("failed parsing response as JSON")?;

    let labels = response.choices.unwrap()[0]
        .message
        .content
        .trim()
        .to_string();
    let labels: Vec<String> = labels
        .split(',')
        .map(|label| label.trim().to_string())
        .collect();

    Ok(labels)
}
