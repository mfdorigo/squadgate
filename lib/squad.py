#!/usr/bin/env python3
"""squadgate support script: demand state, guardrails (hooks), live panel, cost and alerts.

Usage:
  squad.py estado iniciar <id> | encerrar | ativa | listar | custo [session]
  squad.py painel on | off | gerar | avisos [off]
  squad.py hook travas-pre | travas-post | painel | agente | parada   (reads the hook JSON on stdin)

Safety rules of the script itself:
  - Any unexpected error goes to <state>/erros.log and the hook exits 0
    (a bug in this script never blocks the user's work).
  - It only exits 2 on an intentional block.

Runtime state lives outside the repository, in ~/.claude/squad-state (or $SQUADGATE_STATE).
Messages read by Claude are in English; messages read by the user follow the OS language.
"""
import contextlib
import hashlib
import html
import json
import locale
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import traceback
from datetime import datetime

try:
    import fcntl  # macOS / Linux
except ImportError:  # Windows
    fcntl = None

CODE = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
ESTADO = os.environ.get("SQUADGATE_STATE") or os.path.expanduser(os.path.join("~", ".claude", "squad-state"))
SISTEMA = "mac" if sys.platform == "darwin" else ("win" if sys.platform in ("win32", "cygwin", "msys") else "linux")
ATIVAS = os.path.join(ESTADO, "ativas")
PAINEL_FLAG = os.path.join(ESTADO, "painel-ligado")
PAINEL_DIR = os.path.join(ESTADO, "painel")
PAINEL_ESTADO = os.path.join(PAINEL_DIR, "estado.json")
PAINEL_EVENTOS = os.path.join(PAINEL_DIR, "eventos.jsonl")
PAINEL_LOCK = os.path.join(PAINEL_DIR, ".lock")
PAINEL_HTML = os.path.join(PAINEL_DIR, "index.html")
ERROS = os.path.join(ESTADO, "erros.log")

TIPOS = ("feat", "fix", "refactor", "test", "docs", "perf", "build", "ci", "chore", "style", "revert")
RE_TITULO = re.compile(r"^(%s)(\([^()\s]+\))?!?: (.+)$" % "|".join(TIPOS))
RE_GENERICA = re.compile(
    r"^(wip|ajustes?|ajuste geral|pequenos ajustes|corre[cç](õ|o)es( diversas)?|corre[cç][aã]o|"
    r"update|updates|altera[cç](õ|o)es|mudan[cç]as|fix|fixes|teste?s?|melhorias|"
    r"changes|minor (changes|fixes|updates)|small fixes|tweaks|improvements|misc|stuff|cleanup)\.?$"
)


# ----------------------------------------------------------------------------
# idioma (só para o que o usuário lê direto: avisos e /squad custo)
# ----------------------------------------------------------------------------
_IDIOMA = None


def idioma():
    """pt ou en, a partir do idioma do sistema operacional."""
    global _IDIOMA
    if _IDIOMA:
        return _IDIOMA
    valor = os.environ.get("SQUADGATE_LANG") or os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or ""
    if not valor and SISTEMA == "mac":
        try:
            valor = subprocess.run(["defaults", "read", "-g", "AppleLocale"], capture_output=True, text=True, timeout=3).stdout
        except Exception:
            valor = ""
    if not valor:
        try:
            valor = locale.getlocale()[0] or ""
        except Exception:
            valor = ""
    _IDIOMA = "pt" if valor.lower().startswith("pt") or "portuguese" in valor.lower() else "en"
    return _IDIOMA


TEXTOS = {
    "pt": {
        "papeis": {"squad-analista": "Analista", "squad-arquiteto": "Arquiteto",
                   "squad-desenvolvedor": "Desenvolvedor", "squad-qa": "QA", "squad-ux": "UX"},
        "terminou": "%s terminou em %s", "precisa": "Squad precisa de você · %s",
        "pergunta": "Há uma pergunta para você.", "avisos_on": "Avisos ligados.",
        "orq": "Orquestrador", "quem": "Quem", "modelo": "Modelo", "chamadas": "Chamadas", "saida": "Saída",
        "grav": "Cache gravado", "lido": "Cache lido", "total": "Total",
        "sessao": "Sessão `%s`%s · tokens processados: **%s**\n", "desde": " · desde o /squad das %s",
        "fora": "⚠ Orquestrador fora do Sonnet em %d de %d chamadas.", "dentro": "✓ Orquestrador ficou no Sonnet.",
        "bg": "⚠ %d agente(s) rodaram em segundo plano.", "fg": "✓ Nenhum agente em segundo plano.",
        "nota": "Cache lido custa bem menos que saída e cache gravado. O total serve para comparar demandas; não é a cota.",
        "sem_registro": "Não achei registros do Claude Code para esta pasta.",
        "sem_sessao": "Sessão %s não encontrada em %s.", "sem_uso": "Ainda não há uso registrado nesta sessão.",
        "mil": "mil", "mi": "mi", "decimal": ",",
    },
    "en": {
        "papeis": {"squad-analista": "Analyst", "squad-arquiteto": "Architect",
                   "squad-desenvolvedor": "Developer", "squad-qa": "QA", "squad-ux": "UX"},
        "terminou": "%s finished in %s", "precisa": "Squad needs you · %s",
        "pergunta": "There is a question for you.", "avisos_on": "Alerts on.",
        "orq": "Orchestrator", "quem": "Who", "modelo": "Model", "chamadas": "Calls", "saida": "Output",
        "grav": "Cache write", "lido": "Cache read", "total": "Total",
        "sessao": "Session `%s`%s · tokens processed: **%s**\n", "desde": " · since the /squad at %s",
        "fora": "⚠ Orchestrator left Sonnet in %d of %d calls.", "dentro": "✓ Orchestrator stayed on Sonnet.",
        "bg": "⚠ %d agent(s) ran in the background.", "fg": "✓ No agent ran in the background.",
        "nota": "Cache reads cost much less than output and cache writes. Use the total to compare demands; it is not your quota.",
        "sem_registro": "No Claude Code transcripts found for this folder.",
        "sem_sessao": "Session %s not found in %s.", "sem_uso": "No usage recorded in this session yet.",
        "mil": "k", "mi": "M", "decimal": ".",
    },
}


def T(chave):
    return TEXTOS[idioma()][chave]


def nome_papel(tipo):
    return T("papeis").get(tipo, tipo)


# ----------------------------------------------------------------------------
# utilidades
# ----------------------------------------------------------------------------
@contextlib.contextmanager
def trava_arquivo():
    """Exclusão mútua entre hooks simultâneos (fcntl no macOS/Linux, msvcrt no Windows)."""
    os.makedirs(ESTADO, exist_ok=True)
    with open(LOCK, "a+") as f:
        try:
            if fcntl:
                fcntl.flock(f, fcntl.LOCK_EX)
            else:
                import msvcrt
                msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
        except Exception:
            pass
        yield
def git(args, cwd):
    try:
        r = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True, timeout=8)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except Exception as e:  # git ausente, cwd inválido, timeout
        return 1, "", str(e)


def chave_projeto(cwd):
    """Identifica o repositório (o mesmo para a pasta principal e seus worktrees)."""
    if not cwd or not os.path.isdir(cwd):
        return None, None
    rc, common, _ = git(["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd)
    if rc != 0 or not common:
        return None, None
    common = os.path.realpath(common)
    return hashlib.sha1(common.encode()).hexdigest()[:16], common


def demanda_ativa(cwd):
    chave, _ = chave_projeto(cwd)
    if not chave:
        return None
    caminho = os.path.join(ATIVAS, chave + ".json")
    if not os.path.exists(caminho):
        return None
    try:
        with open(caminho) as f:
            return json.load(f)
    except Exception:
        return {"id": "?"}


def registrar_erro():
    try:
        os.makedirs(ESTADO, exist_ok=True)
        with open(ERROS, "a") as f:
            f.write("%s %s\n%s\n" % (datetime.now().isoformat(timespec="seconds"), sys.argv, traceback.format_exc()))
    except Exception:
        pass


def bloquear(motivo, demanda):
    did = (demanda or {}).get("id", "?")
    sys.stderr.write(
        "squadgate guardrail (demand %s): %s\n"
        "Do not try to work around it. Tell the user, in their language, what you were about to do and ask how to proceed.\n" % (did, motivo)
    )
    sys.exit(2)


# ----------------------------------------------------------------------------
# padrão de commit
# ----------------------------------------------------------------------------
def validar_commit(msg):
    msg = (msg or "").strip("\n")
    linhas = msg.split("\n")
    titulo = linhas[0].strip() if linhas else ""
    if titulo.startswith("Merge ") or titulo.startswith('Revert "'):
        return []
    erros = []
    m = RE_TITULO.match(titulo)
    if not m:
        erros.append('title is not in the "type(scope): description" format (types: %s)' % ", ".join(TIPOS))
    else:
        desc = m.group(3).strip().lower()
        if RE_GENERICA.match(desc) or desc.startswith("wip"):
            erros.append('generic description is not allowed ("%s")' % m.group(3).strip())
    if len(titulo) > 72:
        erros.append("title has %d characters (max 72)" % len(titulo))
    if len(linhas) > 1 and linhas[1].strip() != "":
        erros.append("missing blank line between title and body")
    if not re.search(r"(?im)^refs:\s*\S+", msg):
        erros.append('missing footer "Refs: <demand id>"')
    return erros


# ----------------------------------------------------------------------------
# travas
# ----------------------------------------------------------------------------
def segmentos(cmd):
    for seg in re.split(r"&&|\|\||;|\||\n", cmd):
        seg = seg.strip()
        if not seg:
            continue
        try:
            toks = shlex.split(seg)
        except ValueError:
            toks = seg.split()
        # remove sudo, env, variáveis de ambiente no início
        while toks and (toks[0] in ("sudo", "env", "command", "exec", "time", "nohup") or re.match(r"^\w+=", toks[0])):
            toks = toks[1:]
        if toks:
            yield toks


def git_sub(toks):
    """Para 'git -C x -c a=b push ...' devolve (dir, 'push', [args])."""
    i, d = 1, None
    while i < len(toks):
        t = toks[i]
        if t == "-C" and i + 1 < len(toks):
            d, i = toks[i + 1], i + 2
        elif t in ("-c", "--git-dir", "--work-tree", "--namespace") and i + 1 < len(toks):
            i += 2
        elif t.startswith("-"):
            i += 1
        else:
            return d, t, toks[i + 1:]
    return d, None, []


PROD_CLI = {
    "kubectl", "helm", "terraform", "az", "aws", "gcloud", "psql", "mysql", "sqlcmd", "mongosh", "mongo",
    "redis-cli", "ssh", "scp", "rsync", "ansible-playbook", "heroku", "flyctl", "vercel", "firebase",
    "serverless", "sls", "eb", "docker", "kubectx", "oc",
}
RE_PROD = re.compile(r"(^|[^a-z0-9])(prod|production|producao|produção|prd)([^a-z0-9]|$)", re.I)


def checar_comando(cmd, cwd, demanda):
    for toks in segmentos(cmd):
        prog = os.path.basename(toks[0])

        # rm recursivo e forçado
        if prog == "rm":
            flags = ""
            for t in toks[1:]:
                if t == "--":
                    break
                if t.startswith("--"):
                    flags += {"--recursive": "r", "--force": "f"}.get(t, "")
                elif t.startswith("-"):
                    flags += t[1:]
            if ("r" in flags or "R" in flags) and "f" in flags:
                bloquear("`rm -rf` is blocked during a demand.", demanda)

        # comandos contra produção
        if prog in PROD_CLI and RE_PROD.search(" ".join(toks)):
            bloquear("command that looks like it touches production (`%s ...prod...`)." % prog, demanda)
        if prog == "terraform" and any(t in ("apply", "destroy") for t in toks[1:]):
            bloquear("`terraform apply/destroy` is blocked during a demand.", demanda)
        if prog == "kubectl" and "delete" in toks[1:]:
            bloquear("`kubectl delete` is blocked during a demand.", demanda)

        if prog != "git":
            continue
        gdir, sub, args = git_sub(toks)
        repo = os.path.join(cwd, gdir) if gdir and not os.path.isabs(gdir) else (gdir or cwd)

        if sub == "reset" and "--hard" in args:
            bloquear("`git reset --hard` discards work and is blocked during a demand.", demanda)
        if sub == "clean" and any(a.startswith("-") and not a.startswith("--") and "f" in a for a in args):
            bloquear("`git clean -f` deletes files and is blocked during a demand.", demanda)

        if sub == "push":
            for a in args:
                if a in ("-f", "--force", "--mirror", "--all") or (a.startswith("--force") and not a.startswith("--force-with-lease")):
                    bloquear("forced/bulk push (`%s`) is blocked." % a, demanda)
                if a.startswith("+"):
                    bloquear("forced push (refspec with `+`) is blocked.", demanda)
                alvo = a.split(":")[-1]
                if alvo in ("main", "master", "refs/heads/main", "refs/heads/master"):
                    bloquear("pushing directly to `main`/`master` is blocked. Open a PR.", demanda)
            posicionais = [a for a in args if not a.startswith("-")]
            if len(posicionais) <= 1:  # sem refspec: usa a branch atual
                _, atual, _ = git(["rev-parse", "--abbrev-ref", "HEAD"], repo)
                if atual in ("main", "master"):
                    bloquear("you are on `%s`; a direct push is blocked. Open a PR." % atual, demanda)
            # todos os commits que ainda não estão em nenhum remoto precisam seguir o padrão
            rc, saida, _ = git(["log", "--format=%h%x1f%B%x1e", "HEAD", "--not", "--remotes", "-n", "100"], repo)
            if rc == 0 and saida:
                ruins = []
                for bloco in saida.split("\x1e"):
                    bloco = bloco.strip()
                    if not bloco or "\x1f" not in bloco:
                        continue
                    h, msg = bloco.split("\x1f", 1)
                    erros = validar_commit(msg)
                    if erros:
                        ruins.append("%s: %s" % (h, "; ".join(erros)))
                if ruins:
                    bloquear(
                        "commits that do not follow the pattern would be pushed. Fix them before pushing "
                        "(`git commit --amend` for the last one; for an older commit, ask the user):\n  - "
                        + "\n  - ".join(ruins),
                        demanda,
                    )


def hook_travas_pre(dados):
    if dados.get("tool_name") != "Bash":
        return
    cwd = dados.get("cwd") or os.getcwd()
    demanda = demanda_ativa(cwd)
    if not demanda:
        return
    cmd = (dados.get("tool_input") or {}).get("command") or ""
    checar_comando(cmd, cwd, demanda)


def hook_travas_post(dados):
    if dados.get("tool_name") != "Bash":
        return
    cwd = dados.get("cwd") or os.getcwd()
    demanda = demanda_ativa(cwd)
    if not demanda:
        return
    cmd = (dados.get("tool_input") or {}).get("command") or ""
    for toks in segmentos(cmd):
        if os.path.basename(toks[0]) != "git":
            continue
        gdir, sub, _ = git_sub(toks)
        if sub != "commit":
            continue
        repo = os.path.join(cwd, gdir) if gdir and not os.path.isabs(gdir) else (gdir or cwd)
        rc, saida, _ = git(["log", "-1", "--format=%h%x1f%ct%x1f%B"], repo)
        if rc != 0 or "\x1f" not in saida:
            return
        h, ct, msg = saida.split("\x1f", 2)
        if time.time() - int(ct) > 300:  # o commit não aconteceu agora
            return
        erros = validar_commit(msg)
        if erros:
            sys.stderr.write(
                "squadgate guardrail (demand %s): commit %s does not follow the pattern:\n  - %s\n"
                "Fix it now with `git commit --amend` (message via HEREDOC) before going on. "
                "A push with a non-conforming commit will be blocked.\n" % (demanda.get("id", "?"), h, "\n  - ".join(erros))
            )
            sys.exit(2)
        return


# ----------------------------------------------------------------------------
# estado da demanda
# ----------------------------------------------------------------------------
COMANDOS_SEM_DEMANDA = ("custo", "status", "painel", "avisos", "relatorio", "continuar", "cancelar",
                        "cost", "panel", "alerts", "report", "continue", "cancel", "")


def fmt_tokens(n):
    if n >= 1_000_000:
        return ("%.2f " % (n / 1_000_000)).replace(".", T("decimal")) + T("mi")
    if n >= 1000:
        return ("%.1f " % (n / 1000)).replace(".", T("decimal")) + T("mil")
    return str(n)


def nome_modelo(m):
    for k in ("opus", "sonnet", "haiku", "fable"):
        if k in (m or ""):
            return k.capitalize()
    return m or "?"


def glob_jsonl(d):
    return [os.path.join(d, f) for f in os.listdir(d) if f.endswith(".jsonl")]


def pasta_sessoes(cwd):
    """Pasta dos registros do Claude Code para este projeto (tenta a pasta, a raiz git e as pais)."""
    base = os.path.expanduser("~/.claude/projects")
    candidatos = [cwd]
    rc, topo, _ = git(["rev-parse", "--show-toplevel"], cwd)
    if rc == 0 and topo:
        candidatos.append(topo)
    p = cwd
    while p not in ("/", ""):
        p = os.path.dirname(p)
        candidatos.append(p)
    for c in candidatos:
        d = os.path.join(base, re.sub(r"[^A-Za-z0-9]", "-", c))
        if os.path.isdir(d) and glob_jsonl(d):
            return d
    return None


def ler_jsonl(caminho):
    linhas = []
    with open(caminho) as f:
        for l in f:
            try:
                linhas.append(json.loads(l))
            except ValueError:
                pass
    return linhas


def somar_uso(linhas, desde=""):
    """Soma o uso por modelo, contando cada resposta (message.id) uma vez."""
    tot, vistos = {}, set()
    for r in linhas:
        if r.get("type") != "assistant" or r.get("timestamp", "") < desde:
            continue
        m = r.get("message") or {}
        mid = m.get("id")
        if mid in vistos or m.get("model") in (None, "<synthetic>"):
            continue
        vistos.add(mid)
        u = m.get("usage") or {}
        c = tot.setdefault(nome_modelo(m.get("model")), {"chamadas": 0, "saida": 0, "grav": 0, "lido": 0, "entrada": 0})
        c["chamadas"] += 1
        c["saida"] += u.get("output_tokens", 0)
        c["grav"] += u.get("cache_creation_input_tokens", 0)
        c["lido"] += u.get("cache_read_input_tokens", 0)
        c["entrada"] += u.get("input_tokens", 0)
    return tot


def custo(args):
    """Tokens por agente e por modelo na sessão atual (ou na sessão informada)."""
    d = pasta_sessoes(os.getcwd())
    if not d:
        print(T("sem_registro"))
        return 1
    arquivos = glob_jsonl(d)
    if args:
        arquivos = [a for a in arquivos if os.path.basename(a).startswith(args[0])]
        if not arquivos:
            print(T("sem_sessao") % (args[0], d))
            return 1
    sessao = max(arquivos, key=os.path.getmtime)
    linhas = ler_jsonl(sessao)

    # a conta começa no primeiro /squad que iniciou uma demanda (ignora conversa anterior)
    desde, segundo_plano = "", 0
    for r in linhas:
        if r.get("type") != "user":
            continue
        c = (r.get("message") or {}).get("content")
        textos = [c] if isinstance(c, str) else [
            b.get("text") or json.dumps(b.get("content"), ensure_ascii=False)
            for b in (c or []) if isinstance(b, dict)]
        for t in textos:
            t = t or ""
            if not desde and "<command-name>/squad</command-name>" in t:
                a = re.search(r"<command-args>(.*?)</command-args>", t, re.S)
                primeira = (a.group(1).strip().split() or [""])[0] if a else ""
                if primeira not in COMANDOS_SEM_DEMANDA:
                    desde = r.get("timestamp", "")
            if desde and "Async agent launched" in t:
                segundo_plano += 1

    def novo():
        return {"chamadas": 0, "saida": 0, "grav": 0, "lido": 0, "entrada": 0, "vezes": 0}
    linhas_tab = []
    orq = somar_uso(linhas, desde)
    for modelo, c in sorted(orq.items()):
        linhas_tab.append((T("orq"), modelo, c))
    agentes = {}
    pasta_sub = os.path.join(sessao[:-6], "subagents")
    if os.path.isdir(pasta_sub):
        for f in sorted(os.listdir(pasta_sub)):
            if not f.endswith(".meta.json"):
                continue
            meta = ler_json(os.path.join(pasta_sub, f), {})
            sub = ler_jsonl(os.path.join(pasta_sub, f[:-10] + ".jsonl"))
            if not sub or sub[0].get("timestamp", "") < desde:
                continue
            tipo = meta.get("agentType", "?")
            nome = nome_papel(tipo)
            for modelo, c in somar_uso(sub).items():
                a = agentes.setdefault((nome, modelo), novo())
                for k in ("chamadas", "saida", "grav", "lido", "entrada"):
                    a[k] += c[k]
                a["vezes"] += 1
    for (nome, modelo), c in sorted(agentes.items()):
        linhas_tab.append((nome + (" (%d×)" % c["vezes"] if c["vezes"] > 1 else ""), modelo, c))

    if not linhas_tab:
        print(T("sem_uso"))
        return 0

    def total(c):
        return c["saida"] + c["grav"] + c["lido"] + c["entrada"]
    soma = sum(total(c) for _, _, c in linhas_tab)
    try:
        inicio = datetime.fromisoformat(desde.replace("Z", "+00:00")).astimezone().strftime("%H:%M")
    except ValueError:
        inicio = ""
    print(T("sessao") % (os.path.basename(sessao)[:8], (T("desde") % inicio) if inicio else "", fmt_tokens(soma)))
    print("| %s | %s | %s | %s | %s | %s | %s | %% |" % (T("quem"), T("modelo"), T("chamadas"), T("saida"), T("grav"), T("lido"), T("total")))
    print("|---|---|---|---|---|---|---|---|")
    for quem, modelo, c in linhas_tab:
        print("| %s | %s | %d | %s | %s | %s | %s | %d%% |" % (
            quem, modelo, c["chamadas"], fmt_tokens(c["saida"]), fmt_tokens(c["grav"]),
            fmt_tokens(c["lido"]), fmt_tokens(total(c)), round(100 * total(c) / soma) if soma else 0))
    fora = sum(c["chamadas"] for m, c in orq.items() if m != "Sonnet")
    todas = sum(c["chamadas"] for c in orq.values())
    print()
    if fora:
        print(T("fora") % (fora, todas))
    else:
        print(T("dentro"))
    if segundo_plano:
        print(T("bg") % segundo_plano)
    else:
        print(T("fg"))
    print("\n" + T("nota"))
    return 0


def estado(args):
    sub = args[0] if args else ""
    cwd = os.getcwd()
    if sub == "custo":
        return custo(args[1:])
    if sub == "iniciar":
        if len(args) < 2:
            print("usage: squad-estado iniciar <id>")
            return 1
        chave, common = chave_projeto(cwd)
        if not chave:
            print("This folder is not a git repository; guardrails were not turned on.")
            return 1
        _, topo, _ = git(["rev-parse", "--show-toplevel"], cwd)
        _, branch, _ = git(["rev-parse", "--abbrev-ref", "HEAD"], cwd)
        os.makedirs(ATIVAS, exist_ok=True)
        dados = {"id": args[1], "projeto": topo, "git": common, "branch": branch,
                 "inicio": datetime.now().isoformat(timespec="seconds")}
        with open(os.path.join(ATIVAS, chave + ".json"), "w") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
        # o painel.json da demanda muda o tempo todo: fica fora do git só nesta máquina
        try:
            excl = os.path.join(common, "info", "exclude")
            os.makedirs(os.path.dirname(excl), exist_ok=True)
            atual = open(excl).read() if os.path.exists(excl) else ""
            if "docs/demandas/*/painel.json" not in atual:
                with open(excl, "a") as f:
                    f.write(("" if atual.endswith("\n") or not atual else "\n") + "docs/demandas/*/painel.json\n")
        except Exception:
            pass
        print("Guardrails on for %s in %s (branch %s)." % (args[1], topo, branch))
        return 0
    if sub == "encerrar":
        chave, _ = chave_projeto(cwd)
        caminho = os.path.join(ATIVAS, (chave or "x") + ".json")
        if chave and os.path.exists(caminho):
            os.remove(caminho)
            print("Guardrails off for this project.")
        else:
            print("There was no active demand in this project.")
        return 0
    if sub == "ativa":
        d = demanda_ativa(cwd)
        if not d:
            print("none")
            return 1
        print(json.dumps(d, ensure_ascii=False))
        return 0
    if sub == "listar":
        itens = []
        if os.path.isdir(ATIVAS):
            for nome in sorted(os.listdir(ATIVAS)):
                if nome.endswith(".json"):
                    try:
                        with open(os.path.join(ATIVAS, nome)) as f:
                            itens.append(json.load(f))
                    except Exception:
                        pass
        if not itens:
            print("No demand with active guardrails.")
        for d in itens:
            print("%s  %s  (branch %s, since %s)" % (d.get("id"), d.get("projeto"), d.get("branch"), d.get("inicio")))
        return 0
    print("usage: squad-estado iniciar <id> | encerrar | ativa | listar | custo [session]")
    return 1


# ----------------------------------------------------------------------------
# painel (v2)
#   - agentes.json / historico.json: mantidos SEMPRE para qualquer agente (hook "agente"),
#     para a equipe e a previsão funcionarem mesmo se o painel for ligado no meio.
#     Agente fora dos papéis da squad (general-purpose, Explore...) também aparece, marcado
#     como "fora da squad": trabalho em andamento nunca fica invisível no painel.
#   - eventos.jsonl: só gravado com o painel ligado.
#   - dados.js: o que a página lê a cada 3 s. Regerado pelos hooks com o painel ligado.
# ----------------------------------------------------------------------------
AGENTES = os.path.join(ESTADO, "agentes.json")
HISTORICO = os.path.join(ESTADO, "historico.json")
LOCK = os.path.join(ESTADO, ".lock")
PAINEL_DADOS = os.path.join(PAINEL_DIR, "dados.js")
TEMPLATE = os.path.join(CODE, "painel", "template.html")

# papel -> iniciais (nomes e descrições ficam com o painel e com TEXTOS, nos dois idiomas)
PAPEIS = {"squad-analista": "AN", "squad-arquiteto": "AR", "squad-desenvolvedor": "DV", "squad-qa": "QA",
          "squad-ux": "UX"}


def agora():
    return time.time()


def ler_json(caminho, padrao):
    try:
        with open(caminho) as f:
            return json.load(f)
    except Exception:
        return padrao


def gravar_json(caminho, dados):
    tmp = caminho + ".tmp"
    with open(tmp, "w") as f:
        json.dump(dados, f, ensure_ascii=False)
    os.replace(tmp, caminho)


def nome_projeto(cwd):
    """Nome do projeto mesmo quando a sessão entrou numa subpasta (ex.: docs/demandas/<id>)."""
    cwd = (cwd or "").replace("\\", "/").rstrip("/")
    for marca in ("/docs/", "/.claude/worktrees/", "/src/", "/tests/"):
        if marca in cwd + "/":
            cwd = (cwd + "/").split(marca)[0]
            break
    return os.path.basename(cwd) or "?"


def painel_ligado():
    return os.path.exists(PAINEL_FLAG)


def registrar_evento(evento, projeto):
    """evento: {"texto": ...} para atividade de ferramenta, ou {"k": "inicio"|"fim", "tipo", ...} para agentes."""
    linha = json.dumps(dict(evento, t=agora(), projeto=projeto), ensure_ascii=False)
    with open(PAINEL_EVENTOS, "a") as f:
        f.write(linha + "\n")
    try:
        if os.path.getsize(PAINEL_EVENTOS) > 60_000:
            with open(PAINEL_EVENTOS) as f:
                ultimas = f.readlines()[-150:]
            with open(PAINEL_EVENTOS, "w") as f:
                f.writelines(ultimas)
    except Exception:
        pass


def resumo_ferramenta(entrada):
    entrada = entrada or {}
    for chave in ("file_path", "path", "pattern", "url", "query"):
        if entrada.get(chave):
            return str(entrada[chave])
    if entrada.get("command"):
        return str(entrada["command"]).split("\n")[0]
    if entrada.get("description"):
        return str(entrada["description"])
    return ""


AVISOS_OFF = os.path.join(ESTADO, "avisos-desligados")


def _fundo(cmd):
    """Roda um comando sem esperar e sem herdar a saída (o hook sai na hora)."""
    try:
        extra = {"creationflags": 0x08000000} if os.name == "nt" else {"start_new_session": True}
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, **extra)
    except Exception:
        pass


def notificar(titulo, texto, urgente=False):
    """Som e notificação do sistema: macOS, Linux (se houver notify-send/paplay) e Windows (PowerShell)."""
    if os.path.exists(AVISOS_OFF):
        return
    if SISTEMA == "mac":
        def esc(t):
            return t.replace("\\", "\\\\").replace('"', '\\"')
        _fundo(["afplay", "/System/Library/Sounds/%s.aiff" % ("Hero" if urgente else "Glass")])
        _fundo(["osascript", "-e", 'display notification "%s" with title "%s"' % (esc(texto), esc(titulo))])
    elif SISTEMA == "linux":
        if shutil.which("notify-send"):
            _fundo(["notify-send", "-a", "squadgate"] + (["-u", "critical"] if urgente else []) + [titulo, texto])
        som = "/usr/share/sounds/freedesktop/stereo/%s.oga" % ("message-new-instant" if urgente else "complete")
        if shutil.which("paplay") and os.path.exists(som):
            _fundo(["paplay", som])
    else:
        def esc(t):
            return t.replace("'", "''")
        ps = ("[System.Media.SystemSounds]::%s.Play();"
              "[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime]>$null;"
              "$x=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
              "$t=$x.GetElementsByTagName('text');$t.Item(0).AppendChild($x.CreateTextNode('%s'))>$null;"
              "$t.Item(1).AppendChild($x.CreateTextNode('%s'))>$null;"
              "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
              "'{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe')"
              ".Show([Windows.UI.Notifications.ToastNotification]::new($x))"
              % ("Exclamation" if urgente else "Asterisk", esc(titulo), esc(texto)))
        _fundo(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps])


def abrir_no_navegador(caminho):
    if SISTEMA == "mac":
        _fundo(["open", caminho])
    elif SISTEMA == "linux":
        if shutil.which("xdg-open"):
            _fundo(["xdg-open", caminho])
    else:
        try:
            os.startfile(caminho)  # noqa: só existe no Windows
        except Exception:
            _fundo(["cmd", "/c", "start", "", caminho])


def hook_parada(dados):
    """Parada de aprovação (AskUserQuestion) numa demanda ativa: avisa que a squad espera você."""
    cwd = dados.get("cwd") or os.getcwd()
    if not demanda_ativa(cwd):
        return
    perguntas = (dados.get("tool_input") or {}).get("questions") or [{}]
    texto = (perguntas[0].get("question") or T("pergunta")).split(". ")[0]
    notificar(T("precisa") % nome_projeto(cwd), texto[:110], urgente=True)


BLOQUEIOS_AGENTE = os.path.join(ESTADO, "bloqueios-agente.json")


def exigir_primeiro_plano(dados, entrada):
    """Barra agente da squad chamado sem run_in_background: false.

    Em segundo plano, a volta do agente abre um turno novo no modelo padrão da
    sessão (Opus) e a troca de modelo regrava o cache inteiro. Para nunca travar
    o fluxo, só barra uma vez por sessão e papel a cada 2 minutos: se a ferramenta
    não tiver o parâmetro, a segunda chamada igual passa.
    """
    tipo = entrada.get("subagent_type") or ""
    if tipo not in PAPEIS or str(entrada.get("run_in_background")).strip().lower() == "false":
        return
    chave = "%s:%s" % (dados.get("session_id", "?"), tipo)
    with trava_arquivo():
        bloq = {k: v for k, v in ler_json(BLOQUEIOS_AGENTE, {}).items() if agora() - v < 120}
        liberar = chave in bloq
        if not liberar:
            bloq[chave] = agora()
        gravar_json(BLOQUEIOS_AGENTE, bloq)
    if liberar:
        return
    sys.stderr.write(
        "squadgate: repeat this call to agent %s with the parameter run_in_background set to "
        "false (boolean), so it runs in the foreground. Do not drop the parameter: without it the "
        "agent runs in the background, the session switches model and the cost goes up.\n" % tipo)
    sys.exit(2)


def hook_agente(dados):
    """Início e fim dos agentes da squad: equipe ao vivo e histórico de duração (previsão)."""
    os.makedirs(PAINEL_DIR, exist_ok=True)
    evento = dados.get("hook_event_name", "")
    projeto = nome_projeto(dados.get("cwd"))
    entrada = dados.get("tool_input") or {}
    if evento == "PreToolUse":
        exigir_primeiro_plano(dados, entrada)
    evento_painel = None
    with trava_arquivo():
        ag = ler_json(AGENTES, {})
        ag.setdefault("rodando", {})
        ag.setdefault("pendente", {})
        if evento == "PreToolUse":
            tipo = entrada.get("subagent_type") or "general-purpose"
            if tipo:
                ag["pendente"].setdefault(tipo, []).append(entrada.get("description") or "")
                ag["pendente"][tipo] = ag["pendente"][tipo][-4:]
        elif evento == "SubagentStart":
            tipo = dados.get("agent_type") or "general-purpose"
            if tipo:
                fila = ag["pendente"].get(tipo) or []
                ativ = fila.pop(0) if fila else ""
                ag["rodando"][dados.get("agent_id", "?")] = {
                    "tipo": tipo, "inicio": agora(), "atividade": ativ, "projeto": projeto}
                evento_painel = {"k": "inicio", "tipo": tipo, "ativ": ativ}
        elif evento == "SubagentStop":
            a = ag["rodando"].pop(dados.get("agent_id", "?"), None)
            tipo = (a or {}).get("tipo") or dados.get("agent_type") or ""
            if a and tipo:
                duracao = agora() - a["inicio"]
                hist = ler_json(HISTORICO, {})
                hist.setdefault(tipo, []).append(round(duracao))
                hist[tipo] = hist[tipo][-20:]
                gravar_json(HISTORICO, hist)
                evento_painel = {"k": "fim", "tipo": tipo, "dur": round(duracao)}
                notificar("Squad · %s" % projeto, T("terminou") % (nome_papel(tipo), fmt_duracao(duracao)))
        # agentes esquecidos (sessão encerrada no meio) somem depois de 3 h
        for aid in list(ag["rodando"]):
            if agora() - ag["rodando"][aid].get("inicio", 0) > 3 * 3600:
                ag["rodando"].pop(aid)
        gravar_json(AGENTES, ag)
        if painel_ligado():
            if evento_painel:
                registrar_evento(evento_painel, projeto)
            gerar_dados()


def hook_painel(dados):
    """Atividade geral (qualquer ferramenta). Só roda com o painel ligado."""
    os.makedirs(PAINEL_DIR, exist_ok=True)
    tool = dados.get("tool_name", "")
    projeto = nome_projeto(dados.get("cwd"))
    with trava_arquivo():
        if tool not in ("Task", "Agent"):
            registrar_evento({"texto": "%s %s" % (tool, resumo_ferramenta(dados.get("tool_input"))[:140])}, projeto)
        gerar_dados()


def fmt_duracao(seg):
    seg = int(seg)
    if seg < 60:
        return "%ds" % seg
    if seg < 3600:
        return "%dmin %02ds" % (seg // 60, seg % 60)
    return "%dh %02dmin" % (seg // 3600, (seg % 3600) // 60)


def mediana(xs):
    xs = sorted(xs)
    n = len(xs)
    if not n:
        return None
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2.0


def demandas_ativas():
    itens = []
    if os.path.isdir(ATIVAS):
        for nome in sorted(os.listdir(ATIVAS)):
            if nome.endswith(".json"):
                d = ler_json(os.path.join(ATIVAS, nome), None)
                if d:
                    itens.append(d)
    return itens


def atualizar_pagina():
    """Recopia o modelo para a página do painel quando o squadgate foi atualizado.

    Devolve a versão do modelo (mtime): a página aberta compara com a dela e se recarrega sozinha.
    """
    versao = int(os.path.getmtime(TEMPLATE))
    if not os.path.exists(PAINEL_HTML) or os.path.getmtime(PAINEL_HTML) < versao:
        shutil.copyfile(TEMPLATE, PAINEL_HTML)
    return versao


def gerar_dados(desligado=False):
    os.makedirs(PAINEL_DIR, exist_ok=True)
    if desligado:
        saida = {"desligado": True, "geradoEm": agora()}
    else:
        demandas = []
        for d in demandas_ativas():
            proj = d.get("projeto") or ""
            painel_json = ler_json(os.path.join(proj, "docs", "demandas", d.get("id") or "", "painel.json"), None)
            demandas.append({"id": d.get("id"), "projeto": proj, "projetoNome": nome_projeto(proj),
                             "branch": d.get("branch"), "painel": painel_json})
        hist = ler_json(HISTORICO, {})
        agentes = []
        for a in sorted((ler_json(AGENTES, {}).get("rodando") or {}).values(), key=lambda x: x.get("inicio", 0)):
            amostras = hist.get(a.get("tipo")) or []
            agentes.append({"tipo": a.get("tipo"), "iniciais": PAPEIS.get(a.get("tipo"), "··"),
                            "foraDaSquad": a.get("tipo") not in PAPEIS,
                            "atividade": a.get("atividade"), "inicio": a.get("inicio"),
                            "projetoNome": a.get("projeto"),
                            "previsaoSeg": mediana(amostras) if len(amostras) >= 2 else None})
        eventos = []
        try:
            with open(PAINEL_EVENTOS) as f:
                eventos = [json.loads(l) for l in f.readlines()[-25:] if l.strip()]
            eventos.reverse()
        except Exception:
            pass
        saida = {"geradoEm": agora(), "pagina": atualizar_pagina(), "demandas": demandas, "agentes": agentes, "eventos": eventos}
    tmp = PAINEL_DADOS + ".tmp"
    with open(tmp, "w") as f:
        f.write("window.__SQUAD__=" + json.dumps(saida, ensure_ascii=False) + ";\n")
    os.replace(tmp, PAINEL_DADOS)


def painel(args):
    sub = args[0] if args else ""
    os.makedirs(PAINEL_DIR, exist_ok=True)
    if sub == "on":
        open(PAINEL_FLAG, "w").close()
        shutil.copyfile(TEMPLATE, PAINEL_HTML)
        gerar_dados()
        abrir_no_navegador(PAINEL_HTML)
        print("Panel on: %s" % PAINEL_HTML)
        print("If it did not open by itself, open that file in a browser.")
        return 0
    if sub == "off":
        if os.path.exists(PAINEL_FLAG):
            os.remove(PAINEL_FLAG)
        gerar_dados(desligado=True)
        print("Panel off. The panel hooks go back to exiting immediately.")
        return 0
    if sub == "gerar":
        gerar_dados()
        print(PAINEL_DADOS)
        return 0
    if sub == "avisos":
        if (args[1:] or [""])[0] == "off":
            open(AVISOS_OFF, "w").close()
            print("Alerts off.")
        else:
            if os.path.exists(AVISOS_OFF):
                os.remove(AVISOS_OFF)
            notificar("Squad", T("avisos_on"))
            print("Alerts on: sound and notification when an agent finishes and when a gate waits for the user.")
        return 0
    print("usage: squad-painel on | off | gerar | avisos [off]")
    return 1


# ----------------------------------------------------------------------------
def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    grupo, args = sys.argv[1], sys.argv[2:]
    if grupo == "estado":
        return estado(args)
    if grupo == "painel":
        return painel(args)
    if grupo == "hook":
        modo = args[0] if args else ""
        try:
            dados = json.load(sys.stdin)
        except Exception:
            return 0
        try:
            if modo == "travas-pre":
                hook_travas_pre(dados)
            elif modo == "travas-post":
                hook_travas_post(dados)
            elif modo == "painel":
                hook_painel(dados)
            elif modo == "agente":
                hook_agente(dados)
            elif modo == "parada":
                hook_parada(dados)
        except SystemExit:
            raise
        except Exception:
            registrar_erro()
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
