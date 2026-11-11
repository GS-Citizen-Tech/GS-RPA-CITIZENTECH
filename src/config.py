"""Configuração central do robô. Valores ajustáveis e segredos vêm de variáveis de ambiente (.env).

Nada sensível fica no código: credenciais de SMTP, URL e token da API são lidos do .env,
que está no .gitignore. O modelo de referência é o .env.example.
"""
import os
from pathlib import Path

try:  # python-dotenv é opcional: sem ele, usa só as variáveis do sistema
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

RAIZ = Path(__file__).resolve().parent.parent


def _bool(nome, padrao):
    return os.getenv(nome, str(padrao)).strip().lower() in ("1", "true", "sim", "yes")


def _lista(nome, padrao):
    return [x.strip().lower() for x in os.getenv(nome, padrao).split(",") if x.strip()]


class Config:
    def __init__(self, base=RAIZ, **sobrescritas):
        self.base = Path(base)
        # ---------- pastas e arquivos ----------
        self.dir_data = self.base / "data"
        self.dir_snapshots = self.dir_data / "snapshots"
        self.dir_saida = self.base / "output"
        self.dir_emails = self.dir_saida / "emails_enviados"
        self.dir_logs = self.base / "logs"
        self.dir_state = self.base / "state"
        self.arquivo_fontes = self.dir_data / "fontes.json"
        self.arquivo_base = self.dir_data / "base_quem_resolve.json"
        self.arquivo_conhecimento = self.dir_data / "base_conhecimento.jsonl"
        self.arquivo_db = self.dir_data / "quem_resolve.db"
        self.arquivo_treino = self.dir_data / "treino.csv"
        self.arquivo_teste = self.dir_data / "teste_rotulado.csv"
        self.arquivo_gabarito = self.dir_data / "gabarito_ocorrencias.csv"
        self.arquivo_enviados = self.dir_state / "enviados.json"
        self.arquivo_revisao = self.dir_saida / "revisao_humana.csv"
        self.caminho_modelo = self.base / "modelos" / "classificador.joblib"

        # ---------- scraping (RF30/RF31) ----------
        self.user_agent = os.getenv(
            "SCRAPER_USER_AGENT",
            "QuemResolveBot/1.0 (prototipo academico FIAP GS2026; coleta de paginas publicas; baixa frequencia)")
        self.atraso_requisicoes = float(os.getenv("SCRAPER_ATRASO_SEGUNDOS", "2"))
        self.min_caracteres_pagina = int(os.getenv("SCRAPER_MIN_CARACTERES", "300"))
        self.tamanho_chunk = int(os.getenv("CHUNK_MAX_CARACTERES", "700"))

        # ---------- resiliência (vale para HTTP, API e SMTP) ----------
        self.timeout_http = float(os.getenv("TIMEOUT_HTTP", "10"))
        self.tentativas = int(os.getenv("TENTATIVAS", "3"))
        self.backoff_segundos = float(os.getenv("BACKOFF_SEGUNDOS", "1"))
        self.max_falhas_seguidas = int(os.getenv("MAX_FALHAS_SEGUIDAS", "3"))

        # ---------- API do Quem Resolve? (CONTRATOS.md, seção E) ----------
        self.api_base_url = os.getenv("API_BASE_URL", "").strip().rstrip("/")
        self.api_token = os.getenv("API_TOKEN", "").strip()

        # ---------- e-mail (RF33) ----------
        self.smtp_host = os.getenv("SMTP_HOST", "localhost")
        self.smtp_porta = int(os.getenv("SMTP_PORTA", "1025"))
        self.smtp_usuario = os.getenv("SMTP_USUARIO", "")
        self.smtp_senha = os.getenv("SMTP_SENHA", "")
        self.smtp_starttls = _bool("SMTP_STARTTLS", False)
        self.smtp_timeout = float(os.getenv("SMTP_TIMEOUT", "10"))
        self.email_remetente = os.getenv("EMAIL_REMETENTE", "robo@quemresolve.local")
        # Se o SMTP for local e ninguém estiver escutando, sobe o SMTP de teste embutido sozinho
        self.smtp_auto_local = _bool("SMTP_AUTO_LOCAL", True)
        # Trava de segurança: o robô só envia para domínios de teste
        self.dominios_permitidos = _lista("DOMINIOS_DESTINO_PERMITIDOS", "caixa-teste.local")

        # ---------- decisão da IA ----------
        self.limiar_confianca = float(os.getenv("LIMIAR_CONFIANCA", "0.40"))
        self.limiar_etiqueta_docs = float(os.getenv("LIMIAR_ETIQUETA_DOCS", "0.30"))

        for chave, valor in sobrescritas.items():
            if not hasattr(self, chave):
                raise AttributeError(f"Config sem o atributo {chave}")
            setattr(self, chave, valor)

    def criar_pastas(self):
        for p in (self.dir_data, self.dir_snapshots, self.dir_saida, self.dir_emails,
                  self.dir_logs, self.dir_state, self.caminho_modelo.parent):
            p.mkdir(parents=True, exist_ok=True)
