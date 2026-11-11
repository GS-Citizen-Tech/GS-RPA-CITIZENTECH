"""API simulada (mock) no formato de CONTRATOS.md, para testar o caminho "via API" do robô
enquanto a API real do Quem Resolve? não está pronta (RNF13: desenvolvimento por contrato).

Uso isolado:  python -m src.mock_api   (serve em http://127.0.0.1:8156, lendo o SQLite local)
Endpoints: GET /health · GET /ocorrencias?status= · PATCH /ocorrencias/{id}/status
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from src.repositorio import ErroRepositorio, RepositorioSQLite


def criar_servidor(caminho_db, porta=8156, falhar_patch=False):
    repo = RepositorioSQLite(caminho_db)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # silencioso

        def _json(self, status, corpo):
            dados = json.dumps(corpo, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(dados)))
            self.end_headers()
            self.wfile.write(dados)

        def do_GET(self):
            url = urlparse(self.path)
            if url.path == "/health":
                return self._json(200, {"status": "ok", "modulos": {"ocorrencias": "mock"}})
            if url.path == "/ocorrencias":
                status = parse_qs(url.query).get("status", ["pendente_envio"])[0]
                if status != "pendente_envio":
                    return self._json(422, {"detail": "mock só filtra status=pendente_envio"})
                return self._json(200, repo.listar_pendentes())
            self._json(404, {"detail": "não encontrado"})

        def do_PATCH(self):
            partes = urlparse(self.path).path.strip("/").split("/")
            if len(partes) != 3 or partes[0] != "ocorrencias" or partes[2] != "status":
                return self._json(404, {"detail": "não encontrado"})
            if falhar_patch:
                return self._json(503, {"detail": "falha simulada"})
            corpo = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            if corpo.get("status") != "enviada":
                return self._json(422, {"detail": "status inválido"})
            try:
                repo.marcar_enviada(partes[1], corpo.get("observacao", ""))
            except ErroRepositorio as e:
                return self._json(409, {"detail": str(e)})
            self._json(200, {"id": partes[1], "status": "enviada"})

    return ThreadingHTTPServer(("127.0.0.1", porta), Handler)


class MockAPI:
    """Sobe a API simulada numa thread (usado por demo_falhas.py e avaliar.py)."""

    def __init__(self, caminho_db, porta=8156, falhar_patch=False):
        self.servidor = criar_servidor(caminho_db, porta, falhar_patch)
        self.url = f"http://127.0.0.1:{self.servidor.server_address[1]}"

    def __enter__(self):
        threading.Thread(target=self.servidor.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self.servidor.shutdown()
        self.servidor.server_close()


if __name__ == "__main__":
    from src.config import Config
    srv = criar_servidor(Config().arquivo_db)
    print("API simulada em http://127.0.0.1:8156 (Ctrl+C para sair)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
