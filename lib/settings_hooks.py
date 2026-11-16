"""Adds or removes the squadgate hooks in Claude Code's settings.json, keeping every other setting.

Usage: settings_hooks.py add <settings.json> <hooks.json> <hook command> <backup file>
       settings_hooks.py remove <settings.json> <backup file>
Any hook whose command mentions "squad-hook" is treated as a squadgate hook (old or new install).
"""
import json
import os
import shutil
import sys


def carregar(caminho):
    if not os.path.exists(caminho):
        return {}
    with open(caminho, encoding="utf-8") as f:
        texto = f.read().strip()
    return json.loads(texto) if texto else {}


def sem_squad(hooks):
    limpo = {}
    for evento, regras in (hooks or {}).items():
        novas = []
        for regra in regras or []:
            itens = [h for h in regra.get("hooks", []) if "squad-hook" not in str(h.get("command", ""))]
            if itens:
                novas.append(dict(regra, hooks=itens))
        if novas:
            limpo[evento] = novas
    return limpo


def gravar(caminho, dados, backup):
    if os.path.exists(caminho):
        os.makedirs(os.path.dirname(backup), exist_ok=True)
        shutil.copy2(caminho, backup)
    os.makedirs(os.path.dirname(caminho) or ".", exist_ok=True)
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, caminho)


def main():
    acao = sys.argv[1]
    settings = sys.argv[2]
    dados = carregar(settings)
    hooks = sem_squad(dados.get("hooks"))
    if acao == "add":
        _, _, _, modelo, comando, backup = sys.argv
        with open(modelo, encoding="utf-8") as f:
            novos = json.loads(f.read().replace("{{HOOK}}", comando.replace("\\", "\\\\").replace('"', '\\"')))
        for evento, regras in novos.items():
            hooks.setdefault(evento, []).extend(regras)
    else:
        backup = sys.argv[3]
    if hooks:
        dados["hooks"] = hooks
    else:
        dados.pop("hooks", None)
    gravar(settings, dados, backup)


if __name__ == "__main__":
    main()
