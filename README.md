# Ponte

**Mande arquivos de um computador para outro com 3 toques no Shift.**

Aperte **Shift 3 vezes**, a tela escurece, arraste o arquivo e clique no computador de destino.
O outro computador recebe na hora um aviso de **"📥 Arquivo recebido"**, sem precisar aceitar nada.

Funciona no mesmo Wi‑Fi e também entre lugares diferentes, pela internet.

## ⬇️ [Baixar o Ponte.exe para Windows](https://github.com/vlogronaldooliveira/ponte/releases/latest/download/Ponte.exe)

Não precisa instalar nada além dele. Veja como configurar em [Em cada computador](#3-em-cada-computador).

---

## Como funciona

- 🖥 **Mesmo Wi‑Fi:** os computadores se encontram sozinhos e o arquivo vai direto de um para o outro.
- 🌐 **Lugares diferentes:** o arquivo passa por um pequeno servidor (`servidor.py`) que você mesmo coloca no ar, de graça. Ele guarda o arquivo só até o destino baixar e apaga em seguida.
- 🔒 Só se enxergam os computadores com a mesma **palavra do grupo**, que funciona como senha da equipe.
- 📁 Pastas são enviadas como `.zip` automaticamente.
- 📥 Os arquivos recebidos ficam em `Downloads\Recebidos Ponte`.

## Vários escritórios, cada um com o seu acesso

A Ponte pode ser usada por quantos escritórios quiserem, **sem um ver os arquivos do outro**.

- Cada escritório escolhe **a sua própria palavra do grupo** (ex.: `rvr-aguas-lindas-2026`).
- Só os computadores com a mesma palavra se enxergam e trocam arquivos.
- Vários escritórios podem dividir **o mesmo servidor** sem misturar nada, ou cada um pode criar o seu.
- Para entrar um escritório novo: baixe a Ponte, abra e escolha a palavra do grupo na janela de boas-vindas.

Use uma palavra difícil de adivinhar, com pelo menos 10 letras e números, porque ela é a "senha" do escritório.

## Arquivos

| Arquivo | Para que serve |
| --- | --- |
| `ponte.py` | O programa que roda em cada computador |
| `servidor.py` | O servidor para enviar pela internet (opcional) |
| `gerar_exe.bat` | Transforma o `ponte.py` em `Ponte.exe` com dois cliques |
| `requirements.txt` | Lista do que o programa precisa |

## Instalação rápida

### 1. Servidor (só se for usar pela internet)

1. Faça um *fork* deste repositório (botão **Fork**, no alto).
2. Em [render.com](https://render.com), crie um **Web Service** ligado ao seu fork:
   - **Build Command:** `pip install aiohttp`
   - **Start Command:** `python servidor.py`
   - **Instance Type:** Free
3. Abra o endereço `.onrender.com` que o Render der. Se aparecer *"Ponte: servidor no ar."*, está pronto.

### 2. O programa

O `Ponte.exe` é montado **automaticamente** pelo GitHub (aba **Actions**) sempre que o `ponte.py` muda, e aparece em **Releases** para download.
Se preferir montar no seu PC: instale o Python marcando **Add python.exe to PATH** e dê dois cliques em `gerar_exe.bat`.

### 3. Em cada computador

1. [Baixe o Ponte.exe](https://github.com/vlogronaldooliveira/ponte/releases/latest/download/Ponte.exe), coloque em `Documentos\Ponte` e abra.
2. No firewall do Windows, permita em **Redes privadas**.
3. Na janela de boas-vindas, preencha o **nome do computador** e a **palavra do grupo** (igual em todos do escritório). O endereço do servidor já vem preenchido.

Pronto. Aperte **Shift 3x** para enviar.

## Problemas comuns

| O que acontece | O que fazer |
| --- | --- |
| Shift 3x não faz nada | Abra o `Ponte.exe`. Aperte rápido, sem segurar. |
| Não aparece nenhum computador | Confira se a palavra do grupo é idêntica nos dois PCs. |
| PCs no mesmo Wi‑Fi não se veem | Deixe o Wi‑Fi como **Rede privada** no Windows e libere a Ponte no firewall. |
| PCs 🌐 demoram a aparecer | O servidor grátis do Render cochila após 15 min parado; espere cerca de 1 minuto. |

## Avisos

- Não envie o arquivo `ponte_config.json` para cá: ele guarda a palavra do seu grupo.
- No mesmo Wi‑Fi os dados não são criptografados. Use em redes de confiança, nunca em Wi‑Fi público.
- Antivírus podem desconfiar porque o programa observa a tecla Shift (só ela, para o atalho).

## Contribua

Achou um problema ou tem uma ideia? Abra uma **Issue** ou mande um **Pull Request**.
Uso livre: pode copiar, mudar e distribuir.
