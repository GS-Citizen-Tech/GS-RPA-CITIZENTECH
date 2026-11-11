"""Tema: web scraping responsável (RF30) -> Carta de Serviços do SP156 e FAQ do SP Regula.

Boas práticas: respeita o robots.txt, User-Agent identificável, atraso entre requisições ao mesmo
site, timeout, retry com espera exponencial e circuit breaker por site.
Caminho seguro: se o site estiver fora do ar, bloquear a coleta ou entregar uma página que só
funciona com JavaScript, o robô usa o snapshot HTML salvo em data/snapshots/ e registra no log.
Cada coleta online bem-sucedida atualiza o snapshot (sem scripts, estilos e imagens embutidas).
"""
import json
import re
import time
from datetime import datetime
from urllib import robotparser
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from src.resiliencia import CircuitBreaker, CircuitoAberto, FalhaPersistente, com_retry

SECOES_SP156 = ["O QUE É", "QUANDO SOLICITAR", "PÚBLICO-ALVO", "REQUISITOS, DOCUMENTOS E INFORMAÇÕES",
                "PRAZO MÁXIMO", "TAXAS OU PREÇO PÚBLICO", "CANAIS PARA SOLICITAR",
                "CANAIS PARA SOLICITAR O SERVIÇO", "PRINCIPAIS ETAPAS",
                "LEGISLAÇÃO", "OBSERVAÇÕES", "ÓRGÃO RESPONSÁVEL"]
MARCA_JS = re.compile(r"(?i)precisa que o seu navegador tenha javascript|enable javascript|habilite o javascript")


class PaginaInutil(Exception):
    """A página respondeu, mas sem conteúdo útil (ex.: depende de JavaScript)."""


class ErroHTTPDefinitivo(Exception):
    """Erro 4xx (exceto 429): repetir não adianta."""


class Coletor:
    def __init__(self, cfg, logger, relatorio, offline=False):
        self.cfg, self.log, self.rel, self.offline = cfg, logger, relatorio, offline
        self.sessao = requests.Session()
        self.sessao.headers["User-Agent"] = cfg.user_agent
        self.robots = {}
        self.breakers = {}
        self.ultimo_acesso = {}
        self.arquivo_manifesto = cfg.dir_snapshots / "manifesto.json"
        self.manifesto = self._ler_manifesto()

    # ---------- infraestrutura ----------
    def _ler_manifesto(self):
        try:
            return json.loads(self.arquivo_manifesto.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            self.rel.erro(f"Manifesto de snapshots corrompido ({e}); recriando.")
            return {}

    def _salvar_manifesto(self):
        tmp = self.arquivo_manifesto.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.manifesto, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.arquivo_manifesto)

    def _breaker(self, host):
        if host not in self.breakers:
            self.breakers[host] = CircuitBreaker(host, self.cfg.max_falhas_seguidas, self.log)
        return self.breakers[host]

    def _esperar_vez(self, host):
        """Atraso mínimo entre requisições ao mesmo site (cortesia com o servidor)."""
        passado = time.time() - self.ultimo_acesso.get(host, 0)
        if passado < self.cfg.atraso_requisicoes:
            time.sleep(self.cfg.atraso_requisicoes - passado)
        self.ultimo_acesso[host] = time.time()

    def _get(self, url):
        host = urlparse(url).netloc

        def requisicao():
            self._esperar_vez(host)
            r = self.sessao.get(url, timeout=self.cfg.timeout_http)
            if r.status_code == 429 or r.status_code >= 500:
                r.raise_for_status()  # temporário: vale tentar de novo
            return r

        return com_retry(requisicao, tentativas=self.cfg.tentativas, backoff=self.cfg.backoff_segundos,
                         logger=self.log, descricao=f"GET {url}", erros=(requests.RequestException,),
                         breaker=self._breaker(host))

    def permitido_pelo_robots(self, url):
        """True/False conforme o robots.txt. Sem robots.txt (404) = permitido (padrão do protocolo).
        Se o robots.txt não puder ser lido por falha de rede, a exceção sobe e a fonte usa o snapshot."""
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        if base not in self.robots:
            r = self._get(f"{base}/robots.txt")
            rp = robotparser.RobotFileParser()
            if r.status_code == 200:
                rp.parse(r.text.splitlines())
                self.log.info(f"robots.txt de {p.netloc} lido")
            else:
                rp.parse([])  # 404 etc.: sem restrições declaradas
                self.log.info(f"{p.netloc} não publica robots.txt (HTTP {r.status_code}): sem restrições")
            self.robots[base] = rp
        return self.robots[base].can_fetch(self.cfg.user_agent, url)

    # ---------- extração ----------
    @staticmethod
    def _limpar_html(html):
        sopa = BeautifulSoup(html, "lxml")
        for tag in sopa(["script", "style", "noscript", "svg", "iframe"]):
            tag.decompose()
        for img in sopa.find_all("img"):
            if str(img.get("src", "")).startswith("data:"):
                img["src"] = ""
        return sopa

    @staticmethod
    def _linhas(sopa, fonte):
        raiz = sopa.find(id=fonte["container_id"]) if fonte.get("container_id") else None
        texto = (raiz or sopa.body or sopa).get_text("\n", strip=True)
        linhas = [l.strip() for l in texto.split("\n") if l.strip()]
        ini = next((i for i, l in enumerate(linhas) if l.upper() == fonte["inicio"].upper()), None)
        if ini is None:
            raise PaginaInutil(f"marcador de início '{fonte['inicio']}' não encontrado")
        if fonte["tipo"] != "sp156_servico":
            ini += 1  # o marcador é só uma âncora de menu
        linhas = linhas[ini:]
        fim = next((i for i, l in enumerate(linhas) if any(l.startswith(m) for m in fonte["fim"])), len(linhas))
        return linhas[:fim]

    @staticmethod
    def _secoes_sp156(linhas):
        secoes, atual = [], None
        for l in linhas:
            if l.upper() in SECOES_SP156:
                atual = {"secao": l.capitalize(), "linhas": []}  # "O QUE É" -> "O que é"
                secoes.append(atual)
            elif atual:
                atual["linhas"].append(l)
        return [(s["secao"], " ".join(s["linhas"])) for s in secoes if s["linhas"]]

    @staticmethod
    def _secoes_faq(linhas):
        """Pergunta (linha terminada em '?') + resposta até a próxima pergunta."""
        pares, atual = [], None
        for l in linhas:
            if re.match(r"^\w+-feira, \d+ de \w+ de \d{4}|^(Sábado|Domingo), ", l):
                continue  # linha de data de publicação
            if l.endswith("?"):
                atual = [l, []]
                pares.append(atual)
            elif atual:
                atual[1].append(l)
        return [(p, " ".join(r)) for p, r in pares if r]

    @staticmethod
    def _secoes_artigo(linhas):
        corpo = [l for l in linhas if not re.match(r"^\w+-feira, \d+ de \w+ de \d{4}", l)]
        if not corpo:
            return []
        return [(corpo[0][:120], " ".join(corpo[1:]) or corpo[0])]

    def extrair(self, html, fonte):
        sopa = self._limpar_html(html)
        linhas = self._linhas(sopa, fonte)
        separar = {"sp156_servico": self._secoes_sp156, "faq": self._secoes_faq}.get(fonte["tipo"],
                                                                                     self._secoes_artigo)
        secoes = separar(linhas)
        total = sum(len(t) for _, t in secoes)
        if total < self.cfg.min_caracteres_pagina:
            js = MARCA_JS.search(sopa.get_text(" "))
            raise PaginaInutil(f"só {total} caracteres úteis" + (" (página depende de JavaScript)" if js else ""))
        return secoes, str(sopa)

    # ---------- fluxo por fonte ----------
    def _caminho_snapshot(self, fonte):
        return self.cfg.dir_snapshots / f"{fonte['id']}.html"

    def _do_snapshot(self, fonte, motivo):
        caminho = self._caminho_snapshot(fonte)
        if not caminho.exists():
            self.rel.erro(f"[{fonte['id']}] {motivo} e não há snapshot em {caminho.name}: fonte ignorada.")
            self.rel.contadores["fontes_sem_dados"] += 1
            return []
        self.rel.aviso(f"[{fonte['id']}] {motivo}: usando snapshot salvo ({caminho.name}).")
        try:
            secoes, _ = self.extrair(caminho.read_text(encoding="utf-8", errors="replace"), fonte)
        except PaginaInutil as e:
            self.rel.erro(f"[{fonte['id']}] snapshot inutilizável ({e}): fonte ignorada.")
            self.rel.contadores["fontes_sem_dados"] += 1
            return []
        self.rel.contadores["fontes_via_snapshot"] += 1
        data = self.manifesto.get(fonte["id"], {}).get("salvo_em", "desconhecida")
        return self._registros(fonte, secoes, "snapshot", data)

    @staticmethod
    def _registros(fonte, secoes, origem, coletado_em):
        return [{"fonte_id": fonte["id"], "titulo": fonte["titulo"], "url": fonte["url"], "secao": s,
                 "texto": t, "origem": origem, "coletado_em": coletado_em} for s, t in secoes]

    def coletar_fonte(self, fonte):
        if self.offline:
            return self._do_snapshot(fonte, "modo offline")
        try:
            if not self.permitido_pelo_robots(fonte["url"]):
                return self._do_snapshot(fonte, "coleta não permitida pelo robots.txt")
            r = self._get(fonte["url"])
            if r.status_code >= 400:
                raise ErroHTTPDefinitivo(f"HTTP {r.status_code}")
            secoes, html_limpo = self.extrair(r.content, fonte)
        except CircuitoAberto as e:
            return self._do_snapshot(fonte, f"site desligado nesta execução ({e})")
        except FalhaPersistente as e:
            return self._do_snapshot(fonte, f"site indisponível ({str(e)[:120]})")
        except (ErroHTTPDefinitivo, PaginaInutil) as e:
            return self._do_snapshot(fonte, f"página sem conteúdo útil ({e})")
        agora = datetime.now().isoformat(timespec="seconds")
        self._caminho_snapshot(fonte).write_text(html_limpo, encoding="utf-8")
        self.manifesto[fonte["id"]] = {"url": fonte["url"], "salvo_em": agora, "origem": "coleta automática"}
        self.rel.contadores["fontes_online"] += 1
        self.log.info(f"[{fonte['id']}] coletada online: {len(secoes)} seções")
        return self._registros(fonte, secoes, "online", agora)

    def coletar(self, fontes):
        registros = []
        for fonte in fontes:
            try:
                registros += self.coletar_fonte(fonte)
            except Exception as e:  # erro inesperado numa fonte não derruba as outras
                self.rel.erro(f"[{fonte.get('id')}] erro inesperado: {type(e).__name__}: {e}")
                self.rel.contadores["fontes_sem_dados"] += 1
        self._salvar_manifesto()
        return registros


def carregar_fontes(caminho, relatorio):
    try:
        fontes = json.loads(caminho.read_text(encoding="utf-8"))["fontes"]
    except FileNotFoundError:
        relatorio.erro(f"Lista de fontes {caminho.name} não encontrada: nada a coletar.")
        return []
    except (json.JSONDecodeError, KeyError, UnicodeDecodeError) as e:
        relatorio.erro(f"Lista de fontes {caminho.name} inválida ({e}): nada a coletar.")
        return []
    obrigatorios = {"id", "titulo", "url", "tipo", "inicio", "fim"}
    validas = [f for f in fontes if obrigatorios <= f.keys()]
    for f in fontes:
        if not obrigatorios <= f.keys():
            relatorio.erro(f"Fonte ignorada por campos ausentes: {f}")
    return validas
