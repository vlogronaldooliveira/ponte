# -*- coding: utf-8 -*-
"""
PONTE — servidor intermediário (para enviar arquivos entre redes diferentes).

Ele só faz duas coisas:
  1. Diz a cada PC quem mais está online no mesmo grupo.
  2. Guarda o arquivo por pouco tempo até o PC de destino baixar, e apaga em seguida.

Rodar localmente:  python servidor.py   (porta 8080 ou a variável PORT)
"""
import asyncio
import os
import tempfile
import time
import uuid
from pathlib import Path

from aiohttp import web

PASTA = Path(os.environ.get("PONTE_PASTA", tempfile.gettempdir())) / "ponte_relay"
PASTA.mkdir(parents=True, exist_ok=True)
LIMITE = int(os.environ.get("PONTE_LIMITE_MB", "2048")) * 1024 * 1024   # tamanho máximo por arquivo
VALIDADE = int(os.environ.get("PONTE_VALIDADE_HORAS", "24")) * 3600     # apaga se ninguém baixar

clientes = {}   # id -> {"ws", "nome", "token"}
arquivos = {}   # fid -> {"caminho", "nome", "de", "para", "token", "tamanho", "criado"}


def aviso(fid, a):
    return {"tipo": "arquivo", "fid": fid, "nome": a["nome"], "de": a["de"], "tamanho": a["tamanho"]}


async def mandar(ws, dados):
    try:
        await ws.send_json(dados)
    except Exception:
        pass


async def avisar_pares(token):
    do_grupo = [(i, c) for i, c in list(clientes.items()) if c["token"] == token]
    lista = [{"id": i, "nome": c["nome"]} for i, c in do_grupo]
    for i, c in do_grupo:
        await mandar(c["ws"], {"tipo": "pares", "lista": [p for p in lista if p["id"] != i]})


def erro(status, texto):
    return web.json_response({"erro": texto}, status=status)


async def inicio(_req):
    return web.Response(text="Ponte: servidor no ar.")


async def conexao(req):
    token = req.query.get("token", "")
    cid = req.query.get("id", "")
    nome = req.query.get("nome", "PC")[:40]
    if len(token) < 10 or not cid:
        return erro(400, "Conexão inválida.")
    ws = web.WebSocketResponse(heartbeat=25)
    await ws.prepare(req)

    antigo = clientes.get(cid)
    clientes[cid] = {"ws": ws, "nome": nome, "token": token}
    if antigo and antigo["ws"] is not ws:
        await antigo["ws"].close()
    await avisar_pares(token)

    for fid, a in list(arquivos.items()):          # arquivos que chegaram enquanto estava offline
        if a["para"] == cid and a["token"] == token:
            await mandar(ws, aviso(fid, a))
    try:
        async for _ in ws:
            pass
    finally:
        if clientes.get(cid, {}).get("ws") is ws:
            del clientes[cid]
            await avisar_pares(token)
    return ws


async def enviar(req):
    token = req.headers.get("X-Ponte-Token", "")
    para = req.query.get("para", "")
    destino = clientes.get(para)
    if not destino or destino["token"] != token:
        return erro(404, "Esse computador não está online agora.")
    try:
        esperado = int(req.headers.get("X-Ponte-Tamanho", "-1"))
    except ValueError:
        esperado = -1
    if esperado > LIMITE:
        return erro(413, f"Arquivo maior que o limite de {LIMITE // 1048576} MB.")

    fid = uuid.uuid4().hex
    caminho = PASTA / fid
    total = 0
    try:
        with open(caminho, "wb") as f:
            async for bloco in req.content.iter_chunked(1 << 20):
                total += len(bloco)
                if total > LIMITE:
                    raise ValueError("grande")
                f.write(bloco)
    except Exception:
        caminho.unlink(missing_ok=True)
        return erro(400, "O envio foi interrompido.")
    if esperado >= 0 and total != esperado:
        caminho.unlink(missing_ok=True)
        return erro(400, "O arquivo chegou incompleto.")

    a = {"caminho": caminho, "nome": req.query.get("nome", "arquivo")[:200], "de": req.query.get("de", "?")[:40],
         "para": para, "token": token, "tamanho": total, "criado": time.time()}
    arquivos[fid] = a
    if para in clientes:
        await mandar(clientes[para]["ws"], aviso(fid, a))
    return web.json_response({"ok": True})


async def baixar(req):
    a = arquivos.get(req.match_info["fid"])
    if not a or req.headers.get("X-Ponte-Token") != a["token"]:
        return erro(404, "Arquivo não encontrado.")
    return web.FileResponse(a["caminho"], headers={"Content-Type": "application/octet-stream"})


async def recebido(req):
    fid = req.match_info["fid"]
    a = arquivos.get(fid)
    if a and req.headers.get("X-Ponte-Token") == a["token"]:
        arquivos.pop(fid, None)
        a["caminho"].unlink(missing_ok=True)
    return web.json_response({"ok": True})


async def faxina(_app):
    async def rodar():
        while True:
            agora = time.time()
            for fid, a in list(arquivos.items()):
                if agora - a["criado"] > VALIDADE:
                    arquivos.pop(fid, None)
                    a["caminho"].unlink(missing_ok=True)
            await asyncio.sleep(600)
    tarefa = asyncio.create_task(rodar())
    yield
    tarefa.cancel()


def criar_app():
    app = web.Application(client_max_size=LIMITE + 1024)
    app.router.add_get("/", inicio)
    app.router.add_get("/ws", conexao)
    app.router.add_post("/enviar", enviar)
    app.router.add_get("/baixar/{fid}", baixar)
    app.router.add_post("/recebido/{fid}", recebido)
    app.cleanup_ctx.append(faxina)
    return app


if __name__ == "__main__":
    web.run_app(criar_app(), port=int(os.environ.get("PORT", "8080")))
