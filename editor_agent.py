"""
ClipMind - Agente de edição de vídeo no terminal (CLI).

Reaproveita agent.py, a mesma camada de IA usada pela interface web
(server.py), então CLI e navegador compartilham o mesmo loop de tool calling.
"""

import asyncio
import sys

from agent import (
    AgentError,
    MODEL_NAME,
    TOOLS,
    agent_status,
    run_agent_turn,
)


def exibir_ajuda() -> None:
    """Exibe instruções de uso."""
    print("\n" + "=" * 60)
    print("  CLIPMIND - EDITOR DE VÍDEO COM IA")
    print("=" * 60)
    print("\nComandos disponíveis:")
    print("  ajuda  - Mostra esta mensagem de ajuda")
    print("  status - Mostra a conexão com o LM Studio")
    print("  sair   - Encerra o programa")
    print("  exit   - Encerra o programa")
    print("  quit   - Encerra o programa")
    print("\nExemplos de uso:")
    print('  "Analise o vídeo C:/Videos/meu_video.mp4"')
    print('  "Corte o vídeo video.mp4 do 00:01:00 até 00:03:30"')
    print('  "Remova os silêncios de podcast.mp4 e normalize o volume"')
    print('  "Junte intro.mp4 e aula.mp4 em um único vídeo"')
    print('  "Deixe o vídeo vertical para Shorts com fundo desfocado"')
    print('  "Otimize final.mp4 para o YouTube e crie uma thumbnail aos 10s"')
    print('  "Corte os trechos 00:00:05-00:00:12 e 00:02:00-00:02:40 de aula.mp4"')
    print('  "Escreva \'Inscreva-se\' no rodapé do vídeo"')
    print('  "Grave a legenda legenda.srt no vídeo"')
    print('  "Extraia o áudio de musica.mp4 e converta o vídeo para webm"')
    print("\n" + "=" * 60 + "\n")


async def mostrar_evento(event: dict) -> None:
    """Imprime cada ferramenta que a IA chama, em tempo real."""
    kind = event.get("kind")
    if kind == "tool_call":
        args = event.get("args") or {}
        print(f"  [ferramenta] {event['name']}({args})")
    elif kind == "tool_result":
        resultado = str(event.get("result", ""))
        if len(resultado) > 300:
            resultado = resultado[:300] + "..."
        print(f"  [resultado] {resultado}")
    elif kind == "loading":
        print(f"  [carregando modelo] {event.get('progress')}%", end="\r")
    elif kind == "error":
        print(f"  [erro] {event.get('text')}")


async def turno_usuario(texto: str) -> None:
    """Executa um turno do agente e imprime a resposta."""
    print("\nProcessando...\n")
    resposta = await run_agent_turn(texto, mostrar_evento)
    print(f"\nIA: {resposta}\n")


async def mostrar_status() -> None:
    """Mostra o estado da conexão com o LM Studio."""
    status = await agent_status()
    if status.get("connected"):
        print(f"\nLM Studio acessível. Modelo configurado: {status['model']}")
        print(f"Carregados: {status.get('loaded_models') or 'nenhum'}")
        if not status.get("has_matching_model"):
            print("Ajuste com: set CLIPMIND_MODEL=<nome do modelo>")
    else:
        print(f"\nLM Studio inacessível: {status.get('error')}")
    print()


async def principal() -> None:
    """Loop principal do agente de edição."""
    print("\n" + "=" * 60)
    print("  CLIPMIND - Editor de Vídeo Inteligente")
    print("  Powered by LM Studio + FFmpeg")
    print("=" * 60)
    print(f"\nModelo configurado: {MODEL_NAME}")
    print(f"Ferramentas: {len(TOOLS)} registradas (digite 'ajuda' para exemplos)\n")

    status = await agent_status()
    if not status.get("connected"):
        print("AVISO: LM Studio não acessível no início.")
        print("       Abra o LM Studio e inicie o servidor (aba Developer),")
        print("       ou digite 'status' para testar de novo.\n")
    elif not status.get("has_matching_model"):
        print(f"AVISO: modelo '{MODEL_NAME}' não encontrado. Digite 'status'.\n")

    exibir_ajuda()
    print('Digite "ajuda" para ver exemplos, "sair" para encerrar.\n')

    while True:
        try:
            user_input = input("Você: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAté logo!")
            break

        if not user_input:
            continue

        baixa = user_input.lower()
        if baixa in ("sair", "exit", "quit"):
            print("\nAté logo!")
            break
        if baixa == "ajuda":
            exibir_ajuda()
            continue
        if baixa == "status":
            await mostrar_status()
            continue

        try:
            await turno_usuario(user_input)
        except AgentError as e:
            print(f"\n{e}\n")
        except KeyboardInterrupt:
            print("\n\nPedido cancelado. Pode digitar de novo.\n")
        except Exception as e:
            print(f"\nErro inesperado: {type(e).__name__}: {e}\n")


if __name__ == "__main__":
    asyncio.run(principal())
