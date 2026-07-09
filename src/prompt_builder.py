"""
prompt_builder.py

Monta o prompt (system + user) enviado ao llama-server para cada evento do
Wazuh, e formata esse prompt de acordo com o "chat_format" declarado no
models.json (o template de conversa esperado por cada família de modelo).
"""

from __future__ import annotations

from src.wazuh_reader import WazuhEvent

SYSTEM_PROMPT = (
    "Você é um analista de segurança cibernética (SOC) sênior, especializado "
    "em triagem de alertas do Wazuh e no framework MITRE ATT&CK. Sua tarefa é "
    "classificar o evento de segurança fornecido, indicando se é um verdadeiro "
    "positivo, falso positivo, evento benigno ou se necessita investigação "
    "adicional, mapeando-o para a tática e técnica MITRE ATT&CK mais "
    "adequadas quando aplicável. Responda SOMENTE com um objeto JSON válido, "
    "sem nenhum texto antes ou depois, seguindo estritamente o schema exigido."
)


def build_user_prompt(event: WazuhEvent) -> str:
    """Constrói o prompt do usuário com os campos relevantes do evento cru
    do Wazuh, sem nenhuma etapa de pré-processamento em disco."""
    groups = ", ".join(event.rule_groups) if event.rule_groups else "N/A"

    lines = [
        "Classifique o seguinte evento de segurança do Wazuh:",
        "",
        f"- ID do evento: {event.event_id}",
        f"- Regra (rule.id): {event.rule_id}",
        f"- Nível da regra (rule.level): {event.rule_level}",
        f"- Descrição da regra: {event.rule_description}",
        f"- Grupos da regra: {groups}",
        f"- Agente: {event.agent_name}",
        f"- Timestamp: {event.timestamp}",
        f"- Log completo (full_log): {event.full_log}",
    ]

    # Contexto adicional (ex.: eventos SCA/compliance, onde full_log vem
    # vazio e o conteúdo relevante está em outros campos do evento).
    extra = event.extra_context
    if extra:
        lines.append(f"- Contexto adicional: {extra}")

    # Pistas de MITRE ATT&CK já associadas pelo próprio Wazuh à regra, se
    # existirem. Não são a resposta final -- o modelo ainda deve avaliar e
    # pode discordar -- mas ajudam a orientar a classificação.
    if event.mitre_techniques_hint:
        lines.append(
            f"- Técnicas MITRE associadas pelo Wazuh (referência, avalie "
            f"se fazem sentido para este evento específico): "
            f"{', '.join(event.mitre_techniques_hint)}"
        )
    if event.mitre_tactics_hint:
        lines.append(
            f"- Táticas MITRE associadas pelo Wazuh (referência): "
            f"{', '.join(event.mitre_tactics_hint)}"
        )

    lines.append("")
    lines.append("Retorne a classificação no formato JSON exigido.")
    return "\n".join(lines)


def _format_llama3(system: str, user: str) -> str:
    return (
        "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n"
        f"{system}<|eot_id|>"
        "<|start_header_id|>user<|end_header_id|>\n\n"
        f"{user}<|eot_id|>"
        "<|start_header_id|>assistant<|end_header_id|>\n\n"
    )


def _format_mistral(system: str, user: str) -> str:
    # Mistral instruct não tem role "system" nativo; embutimos no bloco [INST].
    return f"<s>[INST] {system}\n\n{user} [/INST]"


def _format_chatml(system: str, user: str) -> str:
    return (
        f"<|im_start|>system\n{system}<|im_end|>\n"
        f"<|im_start|>user\n{user}<|im_end|>\n"
        f"<|im_start|>assistant\n"
    )


def _format_gemma(system: str, user: str) -> str:
    # Gemma não possui role "system" separado; concatenamos ao turno do usuário.
    return (
        f"<start_of_turn>user\n{system}\n\n{user}<end_of_turn>\n"
        f"<start_of_turn>model\n"
    )


def _format_raw(system: str, user: str) -> str:
    return f"{system}\n\n{user}\n\n### RESPOSTA JSON:\n"


_FORMATTERS = {
    "llama-3": _format_llama3,
    "mistral": _format_mistral,
    "chatml": _format_chatml,
    "gemma": _format_gemma,
    "raw": _format_raw,
}


def build_prompt(event: WazuhEvent, chat_format: str) -> str:
    """Retorna o prompt final, já formatado com as tags de template do
    chat_format configurado para o modelo em uso."""
    formatter = _FORMATTERS.get(chat_format)
    if formatter is None:
        supported = ", ".join(sorted(_FORMATTERS.keys()))
        raise ValueError(
            f"chat_format '{chat_format}' não suportado. "
            f"Formatos disponíveis: {supported}"
        )
    user_prompt = build_user_prompt(event)
    return formatter(SYSTEM_PROMPT, user_prompt)
