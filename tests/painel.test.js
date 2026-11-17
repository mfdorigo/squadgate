// Panel rendering tests: runs painel/template.html's script against a tiny DOM stub (no dependencies).
// Run: node tests/painel.test.js
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const assert = require("assert");

const TEMPLATE = fs.readFileSync(path.join(__dirname, "..", "painel", "template.html"), "utf8");
const SCRIPT = TEMPLATE.match(/<script>([\s\S]*)<\/script>/)[1];

// ------------------------------------------------------------------ DOM stub
class Node {
  constructor(tag, attrs) {
    this.tagName = (tag || "#text").toUpperCase();
    this.children = []; this.text = ""; this.attrs = Object.assign({}, attrs || {});
    this.className = this.attrs.class || ""; this.id = this.attrs.id || "";
    this.style = { setProperty() {} }; this.handlers = {}; this.hidden = false; this.title = "";
    this.classList = { toggle() {}, add() {}, remove() {}, contains() { return false; } };
  }
  get textContent() { return this.text + this.children.map((c) => c.textContent).join(""); }
  set textContent(v) { this.text = String(v); this.children = []; }
  appendChild(c) { this.children.push(c); c.parent = this; return c; }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter((c) => c !== this); }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k] == null ? null : this.attrs[k]; }
  addEventListener(ev, fn) { (this.handlers[ev] = this.handlers[ev] || []).push(fn); }
  focus() {}
  click() { (this.handlers.click || []).forEach((fn) => fn({ target: this })); }
}

function montar(dados, idiomaSalvo) {
  const porId = {}, dataI = [], langBtns = [];
  // elements declared in the template's HTML
  const re = /<(\w+)([^>]*)>/g; let m;
  while ((m = re.exec(TEMPLATE.split("<script>")[0]))) {
    const attrs = {}; m[2].replace(/([\w-]+)="([^"]*)"/g, (_, k, v) => { attrs[k] = v; });
    const n = new Node(m[1], attrs);
    if (attrs.id) porId[attrs.id] = n;
    if (attrs["data-i"]) dataI.push(n);
    if (attrs["data-lang"]) langBtns.push(n);
  }
  const store = idiomaSalvo ? { "squad-lang": idiomaSalvo } : {};
  const ctx = {
    console, Date, JSON, Math, String, Promise, setTimeout() {}, setInterval(fn) { ctx.tick = fn; },
    localStorage: { getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = v; } },
    navigator: { language: "pt-BR" },
    location: { reload() { ctx.recarregou = true; } },
    document: {
      documentElement: {}, body: new Node("body"),
      head: { appendChild(s) { ctx.window.__SQUAD__ = dados; s.onload && s.onload(); } },
      getElementById: (id) => porId[id] || (porId[id] = new Node("div", { id })),
      createElement: (t) => new Node(t),
      createTextNode: (t) => { const n = new Node("#text"); n.text = String(t); return n; },
      querySelectorAll: (sel) => (sel === "[data-i]" ? dataI : sel === ".lang button" ? langBtns : []),
      addEventListener() {},
    },
  };
  ctx.window = ctx;
  vm.createContext(ctx);
  vm.runInContext(SCRIPT, ctx);
  const texto = () => Object.values(porId).concat(dataI).map((n) => (n.hidden ? "" : n.textContent)).join("\n");
  const titulos = () => {
    const out = []; const walk = (n) => { if (n.title) out.push(n.title); n.children.forEach(walk); };
    walk(porId.track); return out.join("\n");
  };
  return { ctx, porId, texto, titulos, idioma: (l) => langBtns.find((b) => b.attrs["data-lang"] === l).click() };
}

// ------------------------------------------------------------------ fixtures
const ETAPAS_NOVAS = [
  { id: "E0", status: "concluida" },
  { id: "E1", status: "aguardando", quem: "analista", nota: { pt: "3 perguntas bloqueantes", en: "3 blocking questions" } },
  { id: "E2", status: "pendente", quem: "arquiteto" },
  { id: "E3", status: "pendente", quem: "qa" },
  { id: "E4", status: "pendente", quem: "desenvolvedor",
    blocos: [{ id: "B1", nome: { pt: "Gerar o CSV", en: "Build the CSV" }, status: "pendente", quem: "desenvolvedor" }] },
  { id: "E5", status: "pendente", quem: "arquiteto", rodada: 0 },
  { id: "E6", status: "pendente", quem: "qa" },
];
function dadosCom(painel) {
  return { geradoEm: Date.now() / 1000, pagina: 1, agentes: [], eventos: [],
    demandas: [{ id: "DEM-001", projeto: "/x/automation-platform", projetoNome: "automation-platform", painel }] };
}
const NOVO = {
  id: "DEM-001", tamanho: "G", modo: "normal", situacao: "aguardando", atualizadoEm: new Date().toISOString(),
  titulo: { pt: "Passos do painel", en: "Panel steps" },
  texto: { pt: "História revisada; Analista tem 3 perguntas", en: "Story reviewed; Analyst has 3 questions" },
  proximo: { pt: "Parada 1: aprovar a história", en: "Gate 1: approve the story" },
  pendencias: [{ pt: "Dizer o que entra na Administração", en: "Say what goes into Administration" }],
  etapas: ETAPAS_NOVAS,
};
// painel.json as the orchestrator wrote it before this change (DEM-001, 2026-11-16)
const ANTIGO = {
  id: "DEM-001", titulo: "Passos do painel (planning rápida)", tamanho: "G", modo: "normal", situacao: "aguardando",
  texto: "História revisada; Analista tem 3 perguntas", proximo: "Parada 1: aprovar a história",
  pendencias: ["Dizer o que mais entra na Administração"], atualizadoEm: "2026-11-16T18:05:00-03:00",
  etapas: [{ id: "E0", nome: "Entendimento", status: "concluida" },
    { id: "E1", nome: "História", status: "aguardando", quem: "Analista", nota: "3 perguntas bloqueantes" },
    { id: "E2", nome: "Plano", status: "pendente", quem: "Arquiteto" }, { id: "E3", nome: "Testes", status: "pendente", quem: "QA" },
    { id: "E4", nome: "Implementação", status: "pendente", quem: "Desenvolvedor", blocos: [] },
    { id: "E5", nome: "Revisão", status: "pendente", quem: "Arquiteto", rodada: 0 },
    { id: "E6", nome: "Entrega", status: "pendente", quem: "QA" }],
};

// Portuguese words that must never show with EN selected (labels, step and role names, fixture texts)
const SO_PT = ["História", "Entendimento", "Implementação", "Revisão", "Entrega", "Analista", "Arquiteto",
  "Desenvolvedor", "Parada", "Aguardando", "Etapa", "Equipe", "Precisa", "Pendente", "Administração", "perguntas",
  "Passos do painel", "Gerar o CSV", "ninguém", "Comandos"];
const SO_EN = ["Story", "Understanding", "Analyst", "Architect", "Developer", "Gate", "Waiting", "Step ", "Team",
  "Needs you", "Pending", "Administration", "questions", "Panel steps", "Build the CSV", "nobody", "Commands"];

// ------------------------------------------------------------------ tests
const testes = [];
const teste = (nome, fn) => testes.push([nome, fn]);

teste("EN: the whole panel is in English with the new painel.json", () => {
  const p = montar(dadosCom(NOVO), "en");
  const t = p.texto() + "\n" + p.titulos();
  for (const s of ["Step 2 of 7 · Story", "Panel steps", "Story reviewed; Analyst has 3 questions", "Next: Gate 1: approve the story",
    "Say what goes into Administration", "Understanding", "Implementation", "Delivery", "Analyst · Waiting for you",
    "3 blocking questions", "Build the CSV", "Developer · Pending", "Needs you"]) assert.ok(t.includes(s), "missing: " + s);
  for (const s of SO_PT) assert.ok(!t.includes(s), "Portuguese left in EN: " + s);
});

teste("PT: the whole panel is in Portuguese with the new painel.json", () => {
  const p = montar(dadosCom(NOVO), "pt");
  const t = p.texto() + "\n" + p.titulos();
  for (const s of ["Etapa 2 de 7 · História", "Passos do painel", "História revisada; Analista tem 3 perguntas",
    "Próximo: Parada 1: aprovar a história", "Entendimento", "Analista · Aguardando você", "Gerar o CSV", "Precisa de você"])
    assert.ok(t.includes(s), "missing: " + s);
  for (const s of SO_EN) assert.ok(!t.includes(s), "English left in PT: " + s);
});

teste("switch: clicking EN then PT re-renders everything without reloading", () => {
  const p = montar(dadosCom(NOVO), "pt");
  p.idioma("en");
  assert.ok(p.texto().includes("Step 2 of 7 · Story"));
  assert.ok(!p.texto().includes("História"));
  p.idioma("pt");
  assert.ok(p.texto().includes("Etapa 2 de 7 · História"));
  assert.strictEqual(p.ctx.localStorage.getItem("squad-lang"), "pt");
});

teste("old painel.json (plain strings): fixed parts translate, free texts show as written", () => {
  const p = montar(dadosCom(ANTIGO), "en");
  const t = p.texto();
  assert.ok(t.includes("Step 2 of 7 · Story"));
  assert.ok(t.includes("Analyst · Waiting for you"));
  assert.ok(t.includes("Architect · Pending"));
  assert.ok(t.includes("História revisada; Analista tem 3 perguntas"));
  assert.ok(!t.includes("[object Object]"));
});

teste("missing translation: falls back to the other language, never blank or [object Object]", () => {
  const painel = Object.assign({}, NOVO, { texto: { pt: "Só em português" }, proximo: { en: "Only in English" }, titulo: {} });
  const en = montar(dadosCom(painel), "en").texto();
  assert.ok(en.includes("Só em português"));
  const pt = montar(dadosCom(painel), "pt").texto();
  assert.ok(pt.includes("Only in English"));
  assert.ok(!pt.includes("[object Object]") && !en.includes("[object Object]"));
});

teste("unknown step ids and roles show what was written", () => {
  const painel = Object.assign({}, NOVO, { etapas: [{ id: "X9", nome: { pt: "Extra", en: "Extra step" }, status: "andamento", quem: "Fulano" }] });
  const t = montar(dadosCom(painel), "en").texto();
  assert.ok(t.includes("Step 1 of 1 · Extra step"));
  assert.ok(t.includes("Fulano · Running"));
});

teste("orchestrator role is translated", () => {
  const painel = Object.assign({}, NOVO, { etapas: [{ id: "E0", status: "andamento", quem: "orquestrador" }] });
  assert.ok(montar(dadosCom(painel), "en").texto().includes("Orchestrator · Running"));
  assert.ok(montar(dadosCom(painel), "pt").texto().includes("Orquestrador · Rodando"));
});

teste("UX role is named in both languages", () => {
  const painel = Object.assign({}, NOVO, { etapas: [{ id: "E1", status: "andamento", quem: "ux" }] });
  const en = montar(dadosCom(painel), "en").texto();
  assert.ok(en.includes("UX · Running"));
  assert.ok(montar(dadosCom(painel), "pt").texto().includes("UX · Rodando"));
});

teste("agent outside the squad shows, flagged, instead of disappearing", () => {
  const dados = dadosCom(NOVO);
  dados.agentes = [{ tipo: "general-purpose", iniciais: "··", foraDaSquad: true, atividade: "Prototype", inicio: Date.now() / 1000 }];
  const en = montar(dados, "en").texto();
  assert.ok(en.includes("general-purpose"));
  assert.ok(en.includes("Outside the squad"));
  assert.ok(en.includes("1 agent working"));
  assert.ok(montar(dados, "pt").texto().includes("Fora da squad"));
});

teste("page reloads itself when squadgate updates the template", () => {
  const dados = dadosCom(NOVO);
  const p = montar(dados, "en");
  p.ctx.tick(); // next 3 s refresh, same template version
  assert.ok(!p.ctx.recarregou, "reloaded without a template update");
  dados.pagina = 2; // squadgate updated: dados.js now carries a new template version
  p.ctx.tick();
  assert.ok(p.ctx.recarregou, "panel did not reload after a template update");
});

let falhas = 0;
for (const [nome, fn] of testes) {
  try { fn(); console.log("ok   " + nome); } catch (e) { falhas++; console.log("FAIL " + nome + "\n     " + e.message); }
}
console.log(`\n${testes.length - falhas}/${testes.length} passed`);
process.exit(falhas ? 1 : 0);
