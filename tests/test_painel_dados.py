"""Panel data generation (lib/squad.py). Uses a temporary state folder; never touches ~/.claude/squad-state.

Run: python3 -m unittest discover -s tests
"""
import importlib.util
import json
import os
import shutil
import tempfile
import time
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def carregar_squad(estado):
    os.environ["SQUADGATE_STATE"] = estado
    spec = importlib.util.spec_from_file_location("squad_teste", os.path.join(RAIZ, "lib", "squad.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


NOVO = {
    "id": "DEM-001", "tamanho": "G", "situacao": "aguardando",
    "titulo": {"pt": "Passos do painel", "en": "Panel steps"},
    "texto": {"pt": "História revisada", "en": "Story reviewed"},
    "pendencias": [{"pt": "Dizer o que entra", "en": "Say what goes in"}],
    "etapas": [{"id": "E0", "status": "concluida"}, {"id": "E1", "status": "aguardando", "quem": "analista"}],
}
ANTIGO = {
    "id": "DEM-001", "titulo": "Passos do painel", "texto": "História revisada", "pendencias": ["Dizer o que entra"],
    "etapas": [{"id": "E0", "nome": "Entendimento", "status": "concluida"}],
}


class PainelDados(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="squadgate-teste-")
        self.squad = carregar_squad(os.path.join(self.tmp, "estado"))
        self.projeto = os.path.join(self.tmp, "projeto")
        os.makedirs(os.path.join(self.projeto, "docs", "demandas", "DEM-001"))
        os.makedirs(self.squad.ATIVAS)
        with open(os.path.join(self.squad.ATIVAS, "x.json"), "w") as f:
            json.dump({"id": "DEM-001", "projeto": self.projeto, "branch": "squad/DEM-001"}, f)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        os.environ.pop("SQUADGATE_STATE", None)

    def gravar_painel(self, painel):
        with open(os.path.join(self.projeto, "docs", "demandas", "DEM-001", "painel.json"), "w") as f:
            json.dump(painel, f, ensure_ascii=False)

    def ler_dados(self):
        with open(self.squad.PAINEL_DADOS) as f:
            conteudo = f.read()
        self.assertTrue(conteudo.startswith("window.__SQUAD__="))
        return json.loads(conteudo[len("window.__SQUAD__="):].rstrip().rstrip(";"))

    def test_state_folder_is_temporary(self):
        self.assertTrue(self.squad.ESTADO.startswith(self.tmp))

    def test_bilingual_painel_json_passes_through_unchanged(self):
        self.gravar_painel(NOVO)
        self.squad.gerar_dados()
        self.assertEqual(self.ler_dados()["demandas"][0]["painel"], NOVO)

    def test_old_painel_json_passes_through_unchanged(self):
        self.gravar_painel(ANTIGO)
        self.squad.gerar_dados()
        self.assertEqual(self.ler_dados()["demandas"][0]["painel"], ANTIGO)

    def test_invalid_painel_json_does_not_break_generation(self):
        with open(os.path.join(self.projeto, "docs", "demandas", "DEM-001", "painel.json"), "w") as f:
            f.write('{"titulo": {"pt": "sem fechar"')
        self.squad.gerar_dados()
        self.assertIsNone(self.ler_dados()["demandas"][0]["painel"])

    def test_data_carries_template_version(self):
        self.squad.gerar_dados()
        self.assertEqual(self.ler_dados()["pagina"], int(os.path.getmtime(self.squad.TEMPLATE)))

    def test_outdated_panel_page_is_replaced_by_the_template(self):
        os.makedirs(self.squad.PAINEL_DIR, exist_ok=True)
        with open(self.squad.PAINEL_HTML, "w") as f:
            f.write("<p>old page</p>")
        antigo = os.path.getmtime(self.squad.TEMPLATE) - 60  # page older than the template, as after a git pull
        os.utime(self.squad.PAINEL_HTML, (antigo, antigo))
        self.squad.gerar_dados()
        with open(self.squad.PAINEL_HTML) as a, open(self.squad.TEMPLATE) as b:
            self.assertEqual(a.read(), b.read())

    def test_up_to_date_panel_page_is_left_alone(self):
        os.makedirs(self.squad.PAINEL_DIR, exist_ok=True)
        with open(self.squad.PAINEL_HTML, "w") as f:
            f.write("<p>current page</p>")
        futuro = time.time() + 3600
        os.utime(self.squad.PAINEL_HTML, (futuro, futuro))
        self.squad.gerar_dados()
        with open(self.squad.PAINEL_HTML) as f:
            self.assertEqual(f.read(), "<p>current page</p>")

    def test_panel_off_still_writes_data(self):
        self.squad.gerar_dados(desligado=True)
        self.assertTrue(self.ler_dados()["desligado"])


if __name__ == "__main__":
    unittest.main()
