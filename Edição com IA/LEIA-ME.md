# Edição com IA

Ferramenta simples para editar vídeos **no seu computador**, em português, usando esta conversa com o Claude como central de comandos e uma interface local de apoio. Nada é enviado para a internet: transcrição (Whisper), cortes, legendas e exportação rodam localmente com FFmpeg e Python.

## Pastas

| Pasta | O que vai aqui |
|---|---|
| `1-Material bruto/` | Os vídeos originais. A ferramenta copia o arquivo para cá e **nunca o altera** (o hash SHA-256 é conferido na verificação). |
| `2-Identidade visual e referências/` | `perfis/` (estilos em JSON), `logos/` (coloque aqui a logo oficial em PNG com fundo transparente), `fontes/` (arquivos .ttf opcionais). |
| `3-Projetos e intermediários/` | Um projeto por vídeo: `projeto.json` guarda todas as decisões (transcrição corrigida, cortes, textos, formato…) e pode ser reaberto e alterado sem recomeçar. `transcricao-revisao.txt` é o texto para conferir. `trabalho/` tem arquivos temporários (prévias, legendas .ass). |
| `4-Vídeos exportados/` | Os vídeos finais (MP4 com áudio e legendas embutidas) e o `.srt` ao lado. |
| `ferramenta/` | O programa (`editor/`), a interface (`interface/`) e os instaladores. |

## Instalação (uma vez)

Requisitos: **Python 3.10+** e **FFmpeg** (com libass, que já vem nos pacotes oficiais).

- **Windows 10/11**: clique duas vezes em `ferramenta/instalar.bat`. Ele verifica Python (3.11 a 3.14, 64 bits), FFmpeg e Git, oferece instalar o que faltar pelo `winget`, cria o ambiente virtual, instala as dependências fixadas, confirma o FFmpeg e roda um teste final (renderiza 2 s com legenda numa pasta com espaço e acento). Se algo faltar, ele diz o que instalar e pede para rodar de novo. Para instalar manualmente antes: `winget install --id Python.Python.3.12 -e` e `winget install --id Gyan.FFmpeg -e`, depois feche e abra o terminal.
- **macOS**: `brew install ffmpeg python` e depois, em `ferramenta/`, `bash instalar.sh`.
- **Linux**: `sudo apt install ffmpeg python3-venv` e depois `bash instalar.sh`.

Na primeira transcrição o modelo de voz é baixado (modelo `small`: cerca de 480 MB, uma vez só).

## Como usar

### Pela interface (mais fácil)

Windows: clique duas vezes em `ferramenta/iniciar-interface.bat`. macOS/Linux: `bash ferramenta/iniciar-interface.sh`. Abre `http://127.0.0.1:8765/` só na sua máquina. As seções seguem a ordem do trabalho:

1. **Importar vídeo** (envio do arquivo ou caminho no computador).
2. **Descrever a edição** em português. A ferramenta entende pedidos simples (duração máxima, pausas, legendas, formato, título, encerramento, logo, volume, perfil, cortes por tempo) e lista o que não entendeu, para você pedir ao Claude.
3. **Transcrição e legendas**: transcreve em pt-BR com tempos; palavras incertas vêm com `[?]` e linhas duvidosas ficam amarelas. Corrija na tabela, marque falas inteiras para remover e salve.
4. **Silêncios e cortes**: sugere silêncios para você marcar e aplicar; cortes por tempo; tudo pode ser desfeito.
5. **Formato, enquadramento, textos, logo e áudio**: 16:9, 9:16 ou 1:1; “Ver enquadramento” mostra a área que entra no vídeo; título, encerramento, logo e volume da voz.
6. **Pré-visualizar**: antes e depois, em baixa resolução.
7. **Exportar**: MP4 final + SRT, com conferência automática (abre? tem vídeo e áudio? duração bate com os cortes?). “Verificar projeto” confere também se o original está intacto.

### Pela conversa com o Claude

Diga o que quer, por exemplo: *“Faça uma versão de até 60 segundos, retire pausas longas, coloque legendas e mantenha a ideia principal.”* O Claude usa os comandos abaixo, mostra a transcrição e **propõe os cortes antes de renderizar** quando for preciso eliminar conteúdo.

### Pelo terminal (ative o ambiente: `.venv\Scripts\Activate.ps1` no Windows ou `source .venv/bin/activate`)

```
python -m editor importar "C:\Videos\aula.mp4" --nome aula --perfil consul-sindico
python -m editor transcrever aula                      # pt-BR, com tempos; marca trechos incertos
python -m editor transcricao aula --exportar rev.txt   # edite o texto e devolva com:
python -m editor corrigir aula --arquivo rev.txt       # (ou --id 4 --texto "novo texto")
python -m editor silencios aula                        # sugere; revise e depois:
python -m editor silencios aula --aplicar --ids 1,3
python -m editor cortar aula --remover 0:12-0:18       # ou --remover-falas 3,5-7
python -m editor plano aula                            # falas, o que foi removido, duração prevista
python -m editor audio aula --ganho 3
python -m editor texto aula --titulo "Título" --subtitulo "Sub" --encerramento "Consul Síndico"
python -m editor logo aula --arquivo consul-sindico.png --posicao superior-direita
python -m editor formato aula 9:16 --modo cortar --centro-x 0.5
python -m editor enquadramento aula --tempo 5          # gera imagens para revisar o recorte
python -m editor legendas aula --mostrar               # SRT de prévia já com os cortes
python -m editor descrever aula "até 60 segundos, sem pausas, com legendas, vertical"
python -m editor previsualizar aula
python -m editor exportar aula --formato 16:9 9:16 1:1
python -m editor verificar aula
python -m editor interface
```

## Vídeos de referência (exemplos de edição)

Coloque exemplos de edição que você gosta em `2-Identidade visual e referências/referencias/`. Clique em `ferramenta/referencias.bat` (ou rode `python -m editor referencias`): para cada vídeo ele gera `nome-quadros.jpg` (12 momentos com o tempo) e um `referencias-resumo.txt`. Envie essas imagens na conversa com o Claude para transformar o estilo em um perfil.

## Estilos e elementos visuais (versão 0.2)

Dois estilos reutilizáveis, inspirados nos vídeos de referência e adaptados à identidade Consul Síndico (azul-marinho `#0A1A3C`, dourado `#C2942B`, branco, Montserrat nos títulos e Open Sans nos textos; as fontes estão em `2-Identidade visual e referências/fontes`, licença OFL):

- **Explicativo Institucional** (`explicativo-institucional`): título em blocos, pergunta principal no topo, legenda contínua pequena, identificação do apresentador, tópicos numerados, cartões informativos, resumo final e zoom suave discreto. Recomendado como padrão da Consul Síndico.
- **Insights Dinâmicos** (`insights-dinamicos`): legendas de 1 a 2 palavras no ritmo da fala, palavras-chave grandes, etiquetas de conceitos no topo, imagens de apoio, aproximações mais fortes.
- Os perfis anteriores (`pessoal`, `consul-sindico`, `consul-sindico-reels`) continuam funcionando. Projetos antigos são atualizados automaticamente e ganham uma cópia de segurança (`projeto.backup-v1.json`).

### Elementos disponíveis (seção 5b da interface ou `python -m editor cartoes`)

| Tipo | O que é |
|---|---|
| `titulo` | linhas em caixas brancas no topo, com uma linha de destaque em dourado |
| `pergunta` | pergunta principal numa caixa única no topo |
| `topico` | tópico numerado: número em dourado, nome e descrição curta |
| `palavra` | palavra-chave grande, com contorno e sombra (entra deslizando) |
| `chips` | etiquetas de conceitos em pílulas, aparecendo em sequência |
| `check`, `alerta`, `texto` | caixas de confirmação ✓, alerta ⓘ e texto simples |
| `resumo` | caixa com título e itens numerados (tela final de resumo) |
| `imagem` | imagem de apoio (captura, foto) com cantos arredondados e sombra; arquivos em `2-Identidade visual e referências/imagens` |

Cada elemento tem início e fim no vídeo original, ou é ancorado numa fala (`--fala 5`) ou numa palavra (`--palavra balancete --duracao 1.5`), com posição (topo, centro, abaixo do rosto ou `--y 0.38`), animação (`fade`, `subir`, `nenhuma`), tamanho, cores e um interruptor ativo/inativo. O botão "ver" gera uma imagem de conferência com todos os elementos visíveis naquele instante.

Além dos cartões: **destaques** (palavras que ficam douradas nas legendas), **zoom** (`suave` ou `corte`, por fala ou por tempo), **marca d'água** (@ no canto) e **identificação do apresentador** (nome, cargo e @). A **linha do tempo visual** lista, por fala, legendas, destaques, elementos e zoom. "Sugerir tópicos e destaques" propõe tópicos a partir de enumerações ("primeiro, segundo...") e palavras repetidas, e só aplica depois da sua confirmação.

Exemplos no terminal:

```
python -m editor perfil aula explicativo-institucional
python -m editor cartoes aula --adicionar titulo --texto "Quando uma unidade não paga" --destaque "inadimplência" --inicio 0.5 --fim 6
python -m editor cartoes aula --adicionar pergunta --texto "O que acontece com a conta?" --fala 2
python -m editor cartoes aula --adicionar topico --numero 1 --texto "Agir cedo" --descricao "Contato amigável no primeiro atraso" --fala 16
python -m editor cartoes aula --adicionar palavra --texto "inadimplência" --palavra inadimplência --duracao 1.5
python -m editor cartoes aula --adicionar imagem --imagem captura-noticia.png --fala 10 --tamanho 0.8
python -m editor cartoes aula --adicionar resumo --texto "Resumo" --itens "Agir cedo, Negociar por escrito, Cobrança judicial" --fala 21
python -m editor cartoes aula --editar 3 --posicao centro --animacao subir   |   --desativar 3   |   --previa 3
python -m editor destaques aula inadimplência "cota condominial"
python -m editor zoom aula --adicionar --fala 8 --tipo suave
python -m editor assinatura aula --nome "Davidson Marques" --cargo "Consul Síndico" --handle "@consulsindico" --inicio 1 --fim 6
python -m editor sugerir aula            # mostra sugestões; --aplicar para aplicar
```

Vídeos de demonstração em `4-Vídeos exportados`: `demo-explicativo-institucional-9x16.mp4` e `demo-insights-dinamicos-9x16.mp4` (feitos com o vídeo de teste e a logo de teste).

### Ainda não implementado

- Apresentador em janela reduzida enquanto um infográfico ocupa a tela; infográficos (gráficos de barra, documentos ilustrados).
- Vídeos de apoio (só imagens por enquanto); emojis e ícones como elementos próprios.
- Animações além de aparecer/sumir e subir; zoom que acompanha o rosto (o zoom é centralizado no quadro).
- Cortes rápidos automáticos entre frases; leitura automática do estilo de um vídeo de referência.

## Perfis de estilo

Ficam em `2-Identidade visual e referências/perfis/*.json` e podem ser editados em qualquer editor de texto: fonte, cores, posição e tamanho das legendas, logo, cartão de título e encerramento, cor de fundo do modo “caber”.

- `pessoal.json`: estilo neutro para vídeos pessoais.
- `consul-sindico.json`: institucional, azul-marinho `#0A1A3C`, dourado `#C2942B` e branco `#FFFFFF`. Espera a logo oficial em `logos/consul-sindico.png` (ela **não** é recriada pela ferramenta; o teste usa `logo-de-teste.png`, um marcador).

Para criar outro perfil, copie um dos arquivos com novo nome e altere os valores.

## Regras de honestidade da transcrição

- O Whisper roda com filtro de voz e sem “continuar” texto sobre silêncios, para reduzir invenções.
- Trechos com confiança baixa, possível ausência de fala ou texto repetitivo são marcados como **incertos**; palavras com probabilidade baixa recebem `[?]`.
- Nada é corrigido automaticamente: você (ou o Claude, na conversa) confirma o texto. Trechos incertos não revisados aparecem na verificação como pendência.

## O que ainda não está feito

- Download de redes sociais (yt-dlp) não faz parte desta versão.
- A interpretação de pedidos na interface é por regras simples; pedidos que exigem julgamento (“mantenha a ideia principal”) são decididos na conversa com o Claude.
- Não há reconhecimento de rosto para enquadramento automático: o centro do recorte é ajustado manualmente, com imagem de conferência.
- Testado de ponta a ponta apenas em Linux (ambiente desta sessão). O `instalar.ps1` e os `.bat` foram escritos e revisados para Windows 11, mas ainda não foram executados em uma máquina Windows: o primeiro teste real será o seu.
