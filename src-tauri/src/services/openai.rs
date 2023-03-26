use color_eyre::eyre::Result;
use reqwest::Client;
use serde::Deserialize;
use serde_json::Value;

use crate::get_config;

#[derive(Deserialize, Debug)]
struct ApiResponse {
    choices: Option<Vec<Choice>>,
}

#[derive(Default, Debug, Clone, PartialEq, Deserialize)]
struct Choice {
    text: String,
    index: i64,
    logprobs: Value,
    finish_reason: String,
}


pub async fn generate_tags(prompt: &str) -> Result<Vec<String>> {
    // FIXME - this is just for poc. we don't want to read file everytime we want to make a request.
    let conf = get_config()?;

    let client = Client::new();

    let api_key = conf.openai_api_key;
    let api_url = "https://api.openai.com/v1/completions";

    let prompt = format!("Given the following text, suggest 5 relevant tags:\n\n{}\n\nTags:", prompt);

    let response = client
        .post(api_url)
        .header("Content-Type", "application/json")
        .header("Authorization", format!("Bearer {}", api_key))
        .json(&serde_json::json!({
            "prompt": prompt,
            "n": 1,
            "max_tokens": 50,
            "temperature": 0.5,
            "model": "text-davinci-003",
        }))
        .send()
        .await;

    // FIXME - handle error. only panicking for poc.
    let response = match response {
        Ok(response) => response,
        Err(error) => panic!("Problem: {:?}", error),
    };

    println!("{:#?}", response);

    match response.status() {
        reqwest::StatusCode::OK => {
            println!("Success! {:?}", response);
            let res = response.json::<ApiResponse>().await?;
            let choices = res.choices.unwrap();

            if !choices.is_empty() {
                let tags_text = choices[0].text.trim();
                let tags: Vec<String> = tags_text.split(',').map(|tag| tag.trim().to_string()).collect();

                println!("{:#?}", tags);

                return Ok(tags);
            }
        }
        reqwest::StatusCode::UNAUTHORIZED => {
            panic!("Need to grab a new token");
        }
        _ => {
            panic!("Uh oh! Something unexpected happened. {:#?}", response);
        }
    };


    Ok(vec!("".to_string()))
}
