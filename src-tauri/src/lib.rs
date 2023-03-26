use color_eyre::eyre::Result;

use figment::{
    Figment,
    providers::{Env, Format, Toml},
};

use crate::config::Config;

pub mod config;
pub mod services;

pub fn get_config() -> Result<Config> {
    let conf: Config = Figment::new()
        .merge(Toml::file("BrainSpreadConfig.toml"))
        .merge(Env::prefixed("APP_"))
        .extract()?;
    Ok(conf)
}
