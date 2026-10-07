# -*- coding: utf-8 -*-
"""
PONTE — transferência de arquivos entre PCs da mesma rede, sem barreiras.

Como usar:
  • Deixe o programa aberto em todos os computadores (ele fica invisível).
  • Aperte SHIFT 3 vezes rápido → a tela escurece.
  • Arraste/escolha o(s) arquivo(s) e clique no PC de destino.
  • O outro PC recebe na hora um aviso "Arquivo recebido" com botão para abrir.

Os arquivos chegam em: Downloads\\Recebidos Ponte
Só PCs com a mesma palavra de "grupo" (ponte_config.json) se enxergam.
"""
import hashlib
import json
import os
import queue
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

import tkinter as tk
from tkinter import filedialog

try:  # arrastar e soltar (opcional)
    from tkinterdnd2 import TkinterDnD, DND_FILES
    DND = True
except Exception:
    DND = False

try:  # modo internet (opcional)
    import requests
    import websocket
    NET_LIBS = True
except Exception:
    NET_LIBS = False

# ------------------------------------------------------------------ config
BASE = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
CFG_PATH = BASE / "ponte_config.json"
CFG_PADRAO = {
    "grupo": "minha-rede",                     # mesma palavra em todos os PCs
    "nome": socket.gethostname(),              # como este PC aparece para os outros
    "pasta": str(Path.home() / "Downloads" / "Recebidos Ponte"),
    "servidor": "https://ponte-rvr.onrender.com",  # vazio = só Wi-Fi
}


def carregar_cfg():
    cfg = dict(CFG_PADRAO)
    existia = CFG_PATH.exists()
    if existia:
        try:
            cfg.update(json.loads(CFG_PATH.read_text(encoding="utf-8")))
        except Exception:
            pass
    if not cfg.get("id"):
        cfg["id"] = uuid.uuid4().hex          # identidade fixa deste PC
        existia = False
    if not existia or any(k not in cfg for k in CFG_PADRAO):
        try:
            CFG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
    return cfg


PRIMEIRA_VEZ = not CFG_PATH.exists()
CFG = carregar_cfg()
NOME = CFG["nome"]
PASTA = Path(CFG["pasta"])
TOKEN = hashlib.sha256(("ponte:" + CFG["grupo"]).encode()).hexdigest()[:20]
MEU_ID = CFG["id"]
SERVIDOR = str(CFG.get("servidor") or "").strip().rstrip("/")
PORTA_DESC, PORTA_ARQ = 50505, 50506
BLOCO = 1 << 20  # 1 MB

ui = queue.Queue()          # eventos para a interface (thread principal)
pares = {}                  # id -> {"nome", "ip", "visto"}
pares_lock = threading.Lock()


# ------------------------------------------------------------- descoberta
def anunciar():
    """Avisa a rede, a cada 2 s, que este PC existe."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    msg = json.dumps({"app": "ponte", "id": MEU_ID, "nome": NOME, "token": TOKEN}).encode()
    while True:
        try:
            s.sendto(msg, ("255.255.255.255", PORTA_DESC))
        except OSError:
            pass
        time.sleep(2)


def escutar():
    """Ouve os anúncios dos outros PCs."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("", PORTA_DESC))
    while True:
        try:
            data, (ip, _) = s.recvfrom(2048)
            d = json.loads(data)
        except Exception:
            continue
        if d.get("app") != "ponte" or d.get("token") != TOKEN or d.get("id") == MEU_ID:
            continue
        with pares_lock:
            pares[d["id"]] = {"id": d["id"], "nome": str(d.get("nome", ip))[:40], "ip": ip,
                              "visto": time.time(), "via": "lan"}


pares_net = {}  # id -> {"id","nome","via":"net"} (vindos do servidor)


def pares_ativos():
    """PCs no mesmo Wi-Fi têm prioridade (mais rápido); o resto vem pela internet."""
    agora = time.time()
    with pares_lock:
        vivos = {p["id"]: p for p in pares.values() if agora - p["visto"] < 7}
        for i, p in pares_net.items():
            vivos.setdefault(i, p)
    return sorted(vivos.values(), key=lambda p: (p["via"] != "lan", p["nome"].lower()))


# --------------------------------------------------------------- receber
def nome_seguro(nome):
    nome = os.path.basename(str(nome).replace("\\", "/"))
    nome = "".join(c for c in nome if c not in '<>:"/\\|?*' and ord(c) >= 32).strip(" .")
    return nome or "arquivo"


def caminho_livre(p: Path):
    if not p.exists():
        return p
    i = 2
    while True:
        q = p.with_name(f"{p.stem} ({i}){p.suffix}")
        if not q.exists():
            return q
        i += 1


def criar_servidor():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if os.name != "nt":
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("", PORTA_ARQ))   # falha se o programa já estiver aberto
    srv.listen(8)
    return srv


def servir(srv):
    while True:
        conn, addr = srv.accept()
        threading.Thread(target=receber, args=(conn,), daemon=True).start()


def receber(conn):
    with conn:
        conn.settimeout(30)
        f = conn.makefile("rb")
        try:
            cab = json.loads(f.readline(65536))
        except Exception:
            return
        if cab.get("token") != TOKEN:
            return
        PASTA.mkdir(parents=True, exist_ok=True)
        destino = caminho_livre(PASTA / nome_seguro(cab.get("arquivo")))
        parcial = destino.with_name(destino.name + ".parcial")
        restante = int(cab.get("tamanho", 0))
        try:
            with open(parcial, "wb") as out:
                while restante > 0:
                    bloco = f.read(min(BLOCO, restante))
                    if not bloco:
                        break
                    out.write(bloco)
                    restante -= len(bloco)
        except Exception:
            restante = -1
        if restante == 0:
            parcial.replace(destino)
            try:
                conn.sendall(b"OK")
            except OSError:
                pass
            ui.put(("recebido", str(cab.get("de", "?")), str(destino)))
        else:
            try:
                parcial.unlink()
            except OSError:
                pass


# ----------------------------------------------------------------- enviar
def preparar(caminhos):
    """Pastas viram .zip automaticamente. Retorna [(caminho, temporario?)]."""
    itens = []
    for c in caminhos:
        p = Path(c)
        if p.is_dir():
            tmp = Path(tempfile.mkdtemp())
            z = shutil.make_archive(str(tmp / p.name), "zip", str(p))
            itens.append((Path(z), True))
        elif p.is_file():
            itens.append((p, False))
    return itens


def enviar_arquivos(par, caminhos, progresso=None):
    """par = item de pares_ativos() (ou um IP, para envio direto no Wi-Fi)."""
    if isinstance(par, str):
        par = {"ip": par, "via": "lan"}
    itens = preparar(caminhos)
    if not itens:
        raise RuntimeError("Nenhum arquivo válido selecionado.")
    total = sum(p.stat().st_size for p, _ in itens) or 1
    try:
        if par.get("via") == "net":
            return _enviar_internet(par["id"], itens, total, progresso)
        return _enviar_lan(par["ip"], itens, total, progresso)
    finally:
        for p, temp in itens:
            if temp:
                shutil.rmtree(p.parent, ignore_errors=True)


def _enviar_lan(ip, itens, total, progresso):
    enviados = 0
    for p, _ in itens:
        tamanho = p.stat().st_size
        cab = json.dumps({"token": TOKEN, "de": NOME, "arquivo": p.name,
                          "tamanho": tamanho}, ensure_ascii=False).encode() + b"\n"
        with socket.create_connection((ip, PORTA_ARQ), timeout=10) as s:
            s.settimeout(60)
            s.sendall(cab)
            with open(p, "rb") as f:
                while True:
                    bloco = f.read(BLOCO)
                    if not bloco:
                        break
                    s.sendall(bloco)
                    enviados += len(bloco)
                    if progresso:
                        progresso(enviados / total)
            if s.recv(2) != b"OK":
                raise RuntimeError(f"O outro PC não confirmou o recebimento de {p.name}.")
    return len(itens)


# ------------------------------------------------------- modo internet
class _Leitor:
    """Arquivo que avisa o progresso enquanto é enviado."""
    def __init__(self, caminho, ao_ler):
        self.f = open(caminho, "rb")
        self.tamanho = os.path.getsize(caminho)
        self.ao_ler = ao_ler

    def __len__(self):
        return self.tamanho

    def read(self, n=-1):
        bloco = self.f.read(BLOCO if n is None or n < 0 else min(n, BLOCO))
        if bloco:
            self.ao_ler(len(bloco))
        return bloco

    def close(self):
        self.f.close()


def _enviar_internet(para_id, itens, total, progresso):
    if not (NET_LIBS and SERVIDOR):
        raise RuntimeError("Modo internet não configurado.")
    enviados = [0]

    def ao_ler(n):
        enviados[0] += n
        if progresso:
            progresso(min(enviados[0] / total, 1.0))

    for p, _ in itens:
        leitor = _Leitor(p, ao_ler)
        try:
            r = requests.post(f"{SERVIDOR}/enviar",
                              params={"para": para_id, "de": NOME, "nome": p.name},
                              headers={"X-Ponte-Token": TOKEN, "X-Ponte-Tamanho": str(leitor.tamanho),
                                       "Content-Type": "application/octet-stream"},
                              data=leitor, timeout=(20, 900))
        finally:
            leitor.close()
        if r.status_code != 200:
            try:
                motivo = r.json().get("erro")
            except Exception:
                motivo = None
            raise RuntimeError(motivo or f"Servidor respondeu {r.status_code}.")
    return len(itens)


def _baixar_internet(aviso):
    try:
        PASTA.mkdir(parents=True, exist_ok=True)
        destino = caminho_livre(PASTA / nome_seguro(aviso.get("nome")))
        parcial = destino.with_name(destino.name + ".parcial")
        cab = {"X-Ponte-Token": TOKEN}
        with requests.get(f"{SERVIDOR}/baixar/{aviso['fid']}", headers=cab, stream=True,
                          timeout=(20, 900)) as r:
            r.raise_for_status()
            recebidos = 0
            with open(parcial, "wb") as out:
                for bloco in r.iter_content(BLOCO):
                    out.write(bloco)
                    recebidos += len(bloco)
        if recebidos != int(aviso.get("tamanho", -1)):
            parcial.unlink(missing_ok=True)
            return
        parcial.replace(destino)
        requests.post(f"{SERVIDOR}/recebido/{aviso['fid']}", headers=cab, timeout=20)
        ui.put(("recebido", str(aviso.get("de", "?")), str(destino)))
    except Exception:
        pass  # o servidor guarda o arquivo; tenta de novo na próxima conexão


def conectar_internet():
    """Mantém uma conexão aberta com o servidor (presença + avisos de arquivo)."""
    if not (NET_LIBS and SERVIDOR):
        return
    from urllib.parse import urlencode
    url = SERVIDOR.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
    url += "/ws?" + urlencode({"token": TOKEN, "id": MEU_ID, "nome": NOME})
    baixando = set()

    def ao_receber(_ws, texto):
        try:
            d = json.loads(texto)
        except Exception:
            return
        if d.get("tipo") == "pares":
            novos = {p["id"]: {"id": p["id"], "nome": str(p["nome"])[:40], "via": "net"}
                     for p in d.get("lista", []) if p.get("id") != MEU_ID}
            with pares_lock:
                pares_net.clear()
                pares_net.update(novos)
        elif d.get("tipo") == "arquivo" and d.get("fid") not in baixando:
            baixando.add(d["fid"])
            threading.Thread(target=_baixar_internet, args=(d,), daemon=True).start()

    espera = 2
    while True:
        inicio = time.time()
        try:
            app = websocket.WebSocketApp(url, on_message=ao_receber)
            app.run_forever(ping_interval=20, ping_timeout=10)
        except Exception:
            pass
        with pares_lock:
            pares_net.clear()
        baixando.clear()
        espera = 2 if time.time() - inicio > 60 else min(espera * 2, 60)
        time.sleep(espera)


# ------------------------------------- arquivos selecionados no Explorer
def janela_em_foco():
    if os.name != "nt":
        return 0
    try:
        import ctypes
        return int(ctypes.windll.user32.GetForegroundWindow())
    except Exception:
        return 0


def arquivos_selecionados(hwnd):
    """Arquivos selecionados na pasta (ou Área de Trabalho) que estava em foco ao apertar Shift 3x."""
    if os.name != "nt" or not hwnd:
        return []
    try:
        import ctypes
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        shell = win32com.client.Dispatch("Shell.Application")
        janelas = shell.Windows()
        doc = None
        for w in janelas:
            try:
                if int(w.HWND) == hwnd:
                    doc = w.Document
                    break
            except Exception:
                continue
        if doc is None:   # Área de Trabalho
            nome = ctypes.create_unicode_buffer(64)
            ctypes.windll.user32.GetClassNameW(hwnd, nome, 64)
            if nome.value in ("Progman", "WorkerW"):
                try:
                    r = janelas.FindWindowSW(0, 0, 8, 0, 1)   # SWC_DESKTOP, SWFO_NEEDDISPATCH
                    desk = r[0] if isinstance(r, tuple) else r
                    doc = desk.Document
                except Exception:
                    doc = None
        if doc is None:
            return []
        caminhos = [str(item.Path) for item in doc.SelectedItems()]
        return [c for c in caminhos if os.path.exists(c)]
    except Exception:
        return []


# --------------------------------------------------------- atalho 3x SHIFT
def iniciar_atalho():
    from pynput import keyboard
    shifts = {keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r}
    estado = {"segurando": False, "combo": False, "toques": []}

    def press(k):
        if k in shifts:
            estado["segurando"] = True
        else:
            estado["toques"].clear()
            if estado["segurando"]:
                estado["combo"] = True   # foi Shift+letra, não conta

    def release(k):
        if k not in shifts:
            return
        estado["segurando"] = False
        if estado["combo"]:
            estado["combo"] = False
            estado["toques"].clear()
            return
        agora = time.time()
        t = [x for x in estado["toques"] if agora - x < 0.9] + [agora]
        estado["toques"] = t
        if len(t) >= 3:
            estado["toques"] = []
            ui.put(("abrir", janela_em_foco()))

    keyboard.Listener(on_press=press, on_release=release, daemon=True).start()


# ----------------------------------------------- configurar / reiniciar
SRV = None   # socket do servidor local (fechado ao reiniciar)
CHAVE_RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _comando_programa():
    if getattr(sys, "frozen", False):
        return [sys.executable]
    pyw = Path(sys.executable).with_name("pythonw.exe")
    return [str(pyw if pyw.exists() else sys.executable), str(Path(__file__).resolve())]


def inicia_com_windows():
    if os.name != "nt":
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CHAVE_RUN) as k:
            winreg.QueryValueEx(k, "Ponte")
            return True
    except OSError:
        return False


def definir_inicio_windows(ligar):
    if os.name != "nt":
        return
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CHAVE_RUN, 0, winreg.KEY_SET_VALUE) as k:
        if ligar:
            cmd = " ".join(f'"{p}"' for p in _comando_programa())
            winreg.SetValueEx(k, "Ponte", 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(k, "Ponte")
            except OSError:
                pass


def reiniciar():
    try:
        if SRV:
            SRV.close()
    except Exception:
        pass
    env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")
    subprocess.Popen(_comando_programa(), env=env, close_fds=True)
    os._exit(0)


def sair():
    os._exit(0)


# ------------------------------------------------------------- interface
FONTE = "Segoe UI"


class JanelaConfig:
    """Janela simples para configurar a Ponte, sem mexer em arquivo nenhum."""
    _aberta = None

    def __init__(self, root, primeira=False):
        if JanelaConfig._aberta and JanelaConfig._aberta.winfo_exists():
            JanelaConfig._aberta.lift()
            return
        w = tk.Toplevel(root)
        JanelaConfig._aberta = w
        w.title("Ponte — Configuração")
        w.configure(bg="#ffffff", padx=28, pady=24)
        w.resizable(False, False)
        w.attributes("-topmost", True)

        titulo = "Bem-vindo à Ponte!" if primeira else "Configuração da Ponte"
        tk.Label(w, text=titulo, bg="#ffffff", font=(FONTE, 16, "bold")).pack(anchor="w")
        tk.Label(w, text="Preencha e clique em Salvar. Você só faz isso uma vez.", bg="#ffffff",
                 fg="#555555", font=(FONTE, 10)).pack(anchor="w", pady=(2, 16))

        grupo_atual = "" if CFG["grupo"] == CFG_PADRAO["grupo"] else CFG["grupo"]
        self.nome = self._campo(w, "1. Nome deste computador (como os outros vão ver)",
                                "Ex.: Ronaldo - Notebook, Escritório - Recepção", CFG["nome"])
        self.grupo = self._campo(w, "2. Palavra do grupo (igual em TODOS os computadores)",
                                 "Funciona como senha da equipe. Ex.: rvr-obra-2026", grupo_atual)
        self.servidor = self._campo(w, "3. Endereço do servidor (para enviar pela internet)",
                                    "Já vem preenchido. Apague só se quiser usar apenas no mesmo Wi‑Fi.",
                                    CFG.get("servidor", ""))

        self.auto = tk.BooleanVar(value=True if primeira else inicia_com_windows())
        if os.name == "nt":
            tk.Checkbutton(w, text="Abrir a Ponte sozinha quando o computador ligar", variable=self.auto,
                           bg="#ffffff", font=(FONTE, 10), activebackground="#ffffff").pack(anchor="w", pady=(4, 0))

        tk.Label(w, text=f"Os arquivos recebidos vão para: {PASTA}", bg="#ffffff", fg="#777777",
                 font=(FONTE, 9), wraplength=440, justify="left").pack(anchor="w", pady=(10, 0))
        self.aviso = tk.Label(w, text="", bg="#ffffff", fg="#c62828", font=(FONTE, 10))
        self.aviso.pack(anchor="w", pady=(8, 0))
        tk.Button(w, text="Salvar", command=self.salvar, bg="#2f6fed", fg="white", relief="flat",
                  activebackground="#2559c4", activeforeground="white", font=(FONTE, 12, "bold"),
                  padx=28, pady=6, cursor="hand2").pack(anchor="e", pady=(10, 0))
        w.bind("<Return>", lambda e: self.salvar())
        w.update_idletasks()
        x = (w.winfo_screenwidth() - w.winfo_reqwidth()) // 2
        y = (w.winfo_screenheight() - w.winfo_reqheight()) // 3
        w.geometry(f"+{x}+{y}")
        w.focus_force()

    def _campo(self, pai, rotulo, dica, valor):
        tk.Label(pai, text=rotulo, bg="#ffffff", font=(FONTE, 11, "bold")).pack(anchor="w")
        tk.Label(pai, text=dica, bg="#ffffff", fg="#777777", font=(FONTE, 9)).pack(anchor="w")
        e = tk.Entry(pai, font=(FONTE, 12), width=42, relief="solid", bd=1)
        e.insert(0, valor or "")
        e.pack(anchor="w", pady=(4, 14), ipady=4)
        return e

    def salvar(self):
        nome = self.nome.get().strip()
        grupo = self.grupo.get().strip()
        servidor = self.servidor.get().strip().rstrip("/")
        if not nome:
            self.aviso.config(text="Escreva um nome para este computador.")
            return
        if len(grupo) < 6:
            self.aviso.config(text="A palavra do grupo precisa ter pelo menos 6 letras.")
            return
        if servidor and not servidor.startswith(("http://", "https://")):
            servidor = "https://" + servidor
        novo = dict(CFG, nome=nome[:40], grupo=grupo, servidor=servidor)
        try:
            CFG_PATH.write_text(json.dumps(novo, indent=2, ensure_ascii=False), encoding="utf-8")
            definir_inicio_windows(self.auto.get())
        except Exception as e:
            self.aviso.config(text=f"Não consegui salvar: {e}")
            return
        reiniciar()


def abrir_no_sistema(caminho):
    try:
        if os.name == "nt":
            os.startfile(caminho)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", caminho])
        else:
            subprocess.Popen(["xdg-open", caminho])
    except Exception:
        pass


def toast(root, titulo, texto, caminho=None, segundos=10):
    t = tk.Toplevel(root)
    t.overrideredirect(True)
    t.attributes("-topmost", True)
    t.configure(bg="#1f1f1f", highlightthickness=1, highlightbackground="#3a3a3a")
    tk.Label(t, text=titulo, fg="#ffffff", bg="#1f1f1f", font=(FONTE, 12, "bold"),
             anchor="w").pack(fill="x", padx=16, pady=(14, 2))
    tk.Label(t, text=texto, fg="#cfcfcf", bg="#1f1f1f", font=(FONTE, 10), justify="left",
             anchor="w", wraplength=340).pack(fill="x", padx=16)
    if caminho:
        barra = tk.Frame(t, bg="#1f1f1f")
        barra.pack(fill="x", padx=16, pady=(10, 0))
        for rotulo, alvo in (("Abrir", caminho), ("Abrir pasta", str(Path(caminho).parent))):
            tk.Button(barra, text=rotulo, relief="flat", bg="#2f6fed", fg="white",
                      activebackground="#2559c4", activeforeground="white", font=(FONTE, 10),
                      padx=12, cursor="hand2",
                      command=lambda a=alvo: (abrir_no_sistema(a), t.destroy())).pack(side="left", padx=(0, 8))
    tk.Label(t, text="", bg="#1f1f1f").pack(pady=2)
    t.bind("<Button-1>", lambda e: t.destroy() if e.widget is t else None)
    t.update_idletasks()
    w, h = 380, t.winfo_reqheight()
    t.geometry(f"{w}x{h}+{t.winfo_screenwidth() - w - 20}+{t.winfo_screenheight() - h - 60}")
    t.after(segundos * 1000, lambda: t.winfo_exists() and t.destroy())


class Overlay:
    def __init__(self, root):
        self.root = root
        self.win = None
        self.arquivos = []
        self.enviando = False
        self._assinatura = None

    def abrir(self, arquivos=None):
        if self.win:
            self.win.lift()
            if arquivos:
                self.definir(arquivos)
            return
        w = tk.Toplevel(self.root)
        self.win = w
        self.arquivos, self._assinatura, self.enviando = [], None, False
        w.configure(bg="#000000")
        w.attributes("-fullscreen", True)
        w.attributes("-topmost", True)
        try:
            w.attributes("-alpha", 0.0)
        except tk.TclError:
            pass
        w.bind("<Escape>", lambda e: self.fechar())

        caixa = tk.Frame(w, bg="#000000")
        caixa.place(relx=0.5, rely=0.5, anchor="center")
        tk.Label(caixa, text="Enviar para…", fg="#ffffff", bg="#000000",
                 font=(FONTE, 30, "bold")).pack(pady=(0, 22))
        dica = "Solte o arquivo em cima de um computador  ·  ou clique aqui para escolher" if DND \
            else "Clique aqui para escolher os arquivos"
        self.zona = tk.Label(caixa, text=dica, fg="#d0d0d0", bg="#1a1a1a", font=(FONTE, 14),
                             padx=50, pady=34, cursor="hand2")
        self.zona.pack(fill="x", pady=(0, 26))
        self.zona.bind("<Button-1>", lambda e: self.escolher())
        if DND:
            self.zona.drop_target_register(DND_FILES)
            self.zona.dnd_bind("<<Drop>>", self.soltou)
        self.grade = tk.Frame(caixa, bg="#000000")
        self.grade.pack()
        self.status = tk.Label(caixa, text="", fg="#8fd18f", bg="#000000", font=(FONTE, 13))
        self.status.pack(pady=(22, 0))
        rodape = tk.Frame(caixa, bg="#000000")
        rodape.pack(pady=(28, 0))
        tk.Label(rodape, text=f"Este PC: {NOME}   ·   Esc para voltar   ·", fg="#666666",
                 bg="#000000", font=(FONTE, 10)).pack(side="left")
        for texto, acao in (("⚙ Configurar", self.configurar), ("Fechar a Ponte", sair)):
            b = tk.Label(rodape, text=texto, fg="#9ab8ff", bg="#000000", font=(FONTE, 10, "underline"),
                         cursor="hand2", padx=8)
            b.pack(side="left")
            b.bind("<Button-1>", lambda e, a=acao: a())
        self._fade(0.0)
        self._atualizar_pcs()
        if arquivos:
            self.definir(arquivos)
        w.focus_force()

    def _fade(self, a):
        if not self.win:
            return
        a = min(a + 0.11, 0.88)
        try:
            self.win.attributes("-alpha", a)
        except tk.TclError:
            return
        if a < 0.88:
            self.win.after(15, self._fade, a)

    def _atualizar_pcs(self):
        if not self.win:
            return
        vivos = pares_ativos()
        assinatura = tuple((p["id"], p["nome"], p["via"]) for p in vivos)
        if assinatura != self._assinatura:
            self._assinatura = assinatura
            for filho in self.grade.winfo_children():
                filho.destroy()
            if not vivos:
                tk.Label(self.grade, text="Procurando outros computadores…",
                         fg="#9a9a9a", bg="#000000", font=(FONTE, 13)).grid(row=0, column=0)
            for i, p in enumerate(vivos):
                icone = "🖥" if p["via"] == "lan" else "🌐"
                b = tk.Button(self.grade, text=f"{icone}   {p['nome']}", width=22, relief="flat",
                              bg="#262626", fg="#ffffff", activebackground="#2f6fed",
                              activeforeground="#ffffff", font=(FONTE, 15), pady=14, cursor="hand2",
                              command=lambda par=p: self.enviar_para(par))
                b.grid(row=i // 3, column=i % 3, padx=8, pady=8)
                if DND:   # soltar o arquivo direto em cima do computador
                    b.drop_target_register(DND_FILES)
                    b.dnd_bind("<<DropEnter>>", lambda e, bt=b: (bt.config(bg="#2f6fed"), e.action)[1])
                    b.dnd_bind("<<DropLeave>>", lambda e, bt=b: (bt.config(bg="#262626"), e.action)[1])
                    b.dnd_bind("<<Drop>>", lambda e, par=p, bt=b: self.soltou_em(par, e, bt))
        self.win.after(1000, self._atualizar_pcs)

    def escolher(self):
        if not self.win:
            return
        self.win.attributes("-topmost", False)
        escolhidos = filedialog.askopenfilenames(parent=self.win, title="Escolha os arquivos")
        if self.win:
            self.win.attributes("-topmost", True)
            self.win.focus_force()
        if escolhidos:
            self.definir(list(escolhidos))

    def soltou(self, evento):
        self.definir(list(self.root.tk.splitlist(evento.data)))
        return evento.action

    def soltou_em(self, par, evento, botao=None):
        """Arquivo solto em cima de um computador: envia na hora."""
        if botao is not None:
            botao.config(bg="#262626")
        self.definir(list(self.root.tk.splitlist(evento.data)))
        self.enviar_para(par)
        return evento.action

    def definir(self, caminhos):
        self.arquivos = caminhos
        if len(caminhos) == 1:
            txt = f"✓  {Path(caminhos[0]).name}"
        else:
            txt = f"✓  {len(caminhos)} itens selecionados"
        self.zona.config(text=txt + "\n\nAgora clique no computador de destino", fg="#ffffff")

    def enviar_para(self, par):
        if self.enviando:
            return
        if not self.arquivos:
            self.escolher()
            if not self.arquivos:
                return
        self.enviando = True
        self.status.config(text=f"Enviando para {par['nome']}…", fg="#8fd18f")
        arquivos = list(self.arquivos)

        def tarefa():
            try:
                n = enviar_arquivos(par, arquivos,
                                    lambda f: ui.put(("progresso", par["nome"], f)))
                ui.put(("enviado", par["nome"], n))
            except Exception as e:
                ui.put(("erro", str(e) or e.__class__.__name__))

        threading.Thread(target=tarefa, daemon=True).start()

    def configurar(self):
        self.fechar()
        JanelaConfig(self.root)

    def msg(self, texto, cor="#8fd18f"):
        if self.win:
            self.status.config(text=texto, fg=cor)

    def fechar(self):
        if self.win:
            self.win.destroy()
            self.win = None


def main():
    global SRV
    srv = None
    for _ in range(10):          # ao reiniciar, espera a versão anterior liberar a porta
        try:
            srv = criar_servidor()
            break
        except OSError:
            time.sleep(0.5)
    if srv is None:
        return  # já existe uma Ponte aberta neste PC
    SRV = srv
    PASTA.mkdir(parents=True, exist_ok=True)

    root = TkinterDnD.Tk() if DND else tk.Tk()
    root.withdraw()
    ov = Overlay(root)

    threading.Thread(target=servir, args=(srv,), daemon=True).start()
    threading.Thread(target=anunciar, daemon=True).start()
    threading.Thread(target=escutar, daemon=True).start()
    threading.Thread(target=conectar_internet, daemon=True).start()
    iniciar_atalho()

    def loop():
        try:
            while True:
                ev = ui.get_nowait()
                tipo = ev[0]
                if tipo == "abrir":
                    ov.abrir(arquivos_selecionados(ev[1] if len(ev) > 1 else 0))
                elif tipo == "recebido":
                    _, de, caminho = ev
                    toast(root, "📥  Arquivo recebido", f"{de} enviou: {Path(caminho).name}", caminho)
                elif tipo == "progresso":
                    ov.msg(f"Enviando para {ev[1]}…  {ev[2] * 100:.0f}%")
                elif tipo == "enviado":
                    ov.enviando = False
                    ov.msg(f"✓  Enviado para {ev[1]}")
                    root.after(1100, ov.fechar)
                elif tipo == "erro":
                    ov.enviando = False
                    ov.msg(f"Não deu certo: {ev[1]}", "#ff8a80")
        except queue.Empty:
            pass
        root.after(80, loop)

    loop()
    if PRIMEIRA_VEZ:
        JanelaConfig(root, primeira=True)
    else:
        modo = "Wi‑Fi + internet" if (NET_LIBS and SERVIDOR) else "só no mesmo Wi‑Fi"
        toast(root, "Ponte ativa", f"Aperte SHIFT 3 vezes para enviar arquivos.\n"
                                   f"Este PC aparece como: {NOME}  ({modo})", segundos=6)
    root.mainloop()


if __name__ == "__main__":
    main()
