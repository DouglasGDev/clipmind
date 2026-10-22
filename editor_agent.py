"""
Agente de edição de vídeo usando LM Studio com tool calling real.
Conecta-se ao LM Studio local e permite editar vídeos através de conversa natural.

Usa lms.Chat() para manter histórico de conversa e model.act() para tool calling.
"""

import sys
import lmstudio as lms
from youtube_editor_tools import (
    inspect_video,
    cut_video,
    create_thumbnail,
    optimize_for_youtube,
    remove_silence,
    extract_audio,
)


# ============================================================
# CONFIGURAÇÃO - Altere aqui para usar outro modelo
# ============================================================
MODEL_NAME = "qwen2.5-14b-instruct"  # Modelo recomendado para tool calling
# MODEL_NAME = "qwen2.5-7b-instruct"  # Alternativa mais leve
# ============================================================


SYSTEM_PROMPT = """Você é um assistente especializado em edição de vídeo para YouTube.
Você tem acesso a ferramentas reais que executam FFmpeg para editar vídeos.

Sempre que o usuário pedir uma operação de edição, use a ferramenta apropriada.
Responda em português brasileiro de forma clara e objetiva.

Ferramentas disponíveis:
- inspect_video: Analisar informações do vídeo (duração, resolução, codec, fps, etc)
- cut_video: Cortar vídeo especificando início e fim/duração
- create_thumbnail: Criar capa/thumbnail a partir de um frame do vídeo
- optimize_for_youtube: Otimizar vídeo para upload no YouTube (1080p, H.264, AAC)
- remove_silence: Remover silêncios longos do vídeo
- extract_audio: Extrair áudio do vídeo em formato MP3

Quando o usuário fornecer um caminho de arquivo, use-o exatamente como fornecido.
Se o caminho for relativo, considere que é relativo ao diretório atual de trabalho.
Depois de executar qualquer ferramenta, informe ao usuário onde o arquivo foi salvo.
"""


def carregar_modelo(model_name: str) -> lms.LLM:
    """Carrega o modelo no LM Studio."""
    print(f"Carregando modelo: {model_name}")
    print("Aguarde, isso pode levar alguns segundos...\n")

    try:
        model = lms.llm(model_name)
        print(f"Modelo '{model_name}' carregado com sucesso!\n")
        return model
    except Exception as e:
        print(f"Erro ao carregar modelo '{model_name}': {e}")
        print("\nVerifique se:")
        print("  1. O LM Studio está rodando")
        print("  2. O modelo está baixado e disponível")
        print("  3. O nome do modelo está correto")
        print("\nPara ver modelos disponíveis, execute no LM Studio ou use:")
        print("  lms lm list")
        sys.exit(1)


def exibir_ajuda() -> None:
    """Exibe instruções de uso."""
    print("\n" + "=" * 60)
    print("  CLIPMIND - EDITOR DE VÍDEO COM IA")
    print("=" * 60)
    print("\nComandos disponíveis:")
    print("  ajuda  - Mostra esta mensagem de ajuda")
    print("  sair   - Encerra o programa")
    print("  exit   - Encerra o programa")
    print("  quit   - Encerra o programa")
    print("\nExemplos de uso:")
    print('  "Analise o vídeo C:/Videos/meu_video.mp4"')
    print('  "Corte o vídeo video.mp4 do 00:01:00 até 00:03:30"')
    print('  "Crie uma thumbnail do vídeo vlog.mp4 aos 10 segundos"')
    print('  "Otimize o vídeo final.mp4 para o YouTube"')
    print('  "Remova os silêncios do vídeo podcast.mp4"')
    print('  "Extraia o áudio do vídeo musica.mp4"')
    print('  "Corte o vídeo aula.mp4 começando em 00:05:00 com duração de 2 minutos"')
    print("\n" + "=" * 60 + "\n")


def on_message(message) -> None:
    """
    Callback para exibir mensagens durante o processamento do agente.
    Mostra quando ferramentas são chamadas e seus resultados.
    """
    if not hasattr(message, 'content') or not message.content:
        return

    content = message.content

    if isinstance(content, list):
        for item in content:
            if not hasattr(item, 'type'):
                continue
            if item.type == "tool_call":
                print(f"  [Ferramenta] Chamando: {item.name}")
            elif item.type == "tool_result":
                resultado = str(item.content)
                if len(resultado) > 300:
                    resultado = resultado[:300] + "..."
                print(f"  [Resultado] {resultado}")


def main() -> None:
    """Loop principal do agente de edição."""
    print("\n" + "=" * 60)
    print("  CLIPMIND - Editor de Vídeo Inteligente")
    print("  Powered by LM Studio + FFmpeg")
    print("=" * 60)

    # Carrega o modelo
    model = carregar_modelo(MODEL_NAME)

    # Lista de ferramentas disponíveis (funções Python com docstrings)
    tools = [
        inspect_video,
        cut_video,
        create_thumbnail,
        optimize_for_youtube,
        remove_silence,
        extract_audio,
    ]

    exibir_ajuda()

    # Cria o objeto Chat com o system prompt
    # O Chat mantém o histórico de conversa entre chamadas do .act()
    chat = lms.Chat(SYSTEM_PROMPT)

    print("Estou pronto! Digite sua pergunta ou comando de edição.")
    print('Digite "ajuda" para ver exemplos, "sair" para encerrar.\n')

    while True:
        try:
            # Lê entrada do usuário
            user_input = input("Você: ").strip()

            if not user_input:
                continue

            # Verifica comandos de saída
            if user_input.lower() in ("sair", "exit", "quit"):
                print("\nAté logo!")
                break

            # Verifica comando de ajuda
            if user_input.lower() == "ajuda":
                exibir_ajuda()
                continue

            # Adiciona mensagem do usuário ao histórico do chat
            chat.add_user_message(user_input)

            # Executa o agente com tool calling
            # O .act() roda o loop completo: LLM decide ferramenta -> executa -> responde
            print("\nProcessando...\n")

            model.act(
                chat,
                tools,
                on_message=on_message,
            )

            # Após o .act(), a última mensagem no chat é a resposta do assistente
            # Extrai o texto da resposta final
            ultima_msg = chat.history[-1] if chat.history else None

            if ultima_msg and ultima_msg.get("role") == "assistant":
                resposta = ultima_msg.get("content", "")
                if isinstance(resposta, list):
                    # Alguns modelos retornam conteúdo como lista de blocos
                    textos = [
                        bloco.get("text", str(bloco))
                        for bloco in resposta
                        if isinstance(bloco, dict) and bloco.get("type") == "text"
                    ]
                    resposta = "\n".join(textos) if textos else str(resposta)
                print(f"\nIA: {resposta}\n")
            else:
                print("\nIA: (resposta não disponível)\n")

        except KeyboardInterrupt:
            print("\n\nEncerrando...")
            break
        except Exception as e:
            print(f"\nErro: {e}")
            print("Tente novamente ou digite 'sair' para encerrar.\n")


if __name__ == "__main__":
    main()
