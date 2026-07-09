"""
config_loader.py

Responsável por carregar e validar os três arquivos de configuração do
projeto: models.json, system_params.json e inference_params.json.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path


class ConfigError(Exception):
    """Erro de configuração (arquivo ausente, mal formado ou inválido)."""


@dataclass
class ModelConfig:
    alias: str
    gguf_path: str
    server_host: str
    server_port: int
    chat_format: str
    context_length: int
    description: str = ""

    @property
    def server_url(self) -> str:
        return f"http://{self.server_host}:{self.server_port}"


def _load_json(path: Path) -> dict:
    if not path.exists():
        raise ConfigError(f"Arquivo de configuração não encontrado: {path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise ConfigError(f"Erro ao interpretar JSON em {path}: {e}") from e


def load_models(config_dir: Path) -> dict[str, ModelConfig]:
    data = _load_json(config_dir / "models.json")
    models_raw = data.get("models", {})
    if not models_raw:
        raise ConfigError("Nenhum modelo definido em config/models.json")

    models: dict[str, ModelConfig] = {}
    required_fields = ["gguf_path", "server_host", "server_port", "chat_format", "context_length"]
    for alias, cfg in models_raw.items():
        missing = [f for f in required_fields if f not in cfg]
        if missing:
            raise ConfigError(
                f"Modelo '{alias}' em models.json está incompleto. "
                f"Campos ausentes: {missing}"
            )
        models[alias] = ModelConfig(
            alias=alias,
            gguf_path=cfg["gguf_path"],
            server_host=cfg["server_host"],
            server_port=cfg["server_port"],
            chat_format=cfg["chat_format"],
            context_length=cfg["context_length"],
            description=cfg.get("description", ""),
        )
    return models


def get_model(config_dir: Path, alias: str) -> ModelConfig:
    models = load_models(config_dir)
    if alias not in models:
        available = ", ".join(sorted(models.keys()))
        raise ConfigError(
            f"Modelo '{alias}' não encontrado em config/models.json. "
            f"Modelos disponíveis: {available}"
        )
    return models[alias]


def load_system_params(config_dir: Path, model_alias: str | None = None) -> dict:
    data = _load_json(config_dir / "system_params.json")
    params = dict(data.get("defaults", {}))
    if model_alias:
        overrides = data.get("overrides", {}).get(model_alias, {})
        overrides = {k: v for k, v in overrides.items() if not k.startswith("_")}
        params.update(overrides)
    return params


def load_inference_params(config_dir: Path) -> dict:
    data = _load_json(config_dir / "inference_params.json")
    # Remove chaves de documentação (prefixo "_") antes de devolver.
    return {k: v for k, v in data.items() if not k.startswith("_")}


def fail(message: str) -> None:
    """Imprime um erro de configuração de forma amigável e encerra o programa."""
    print(f"[ERRO DE CONFIGURAÇÃO] {message}", file=sys.stderr)
    sys.exit(1)
