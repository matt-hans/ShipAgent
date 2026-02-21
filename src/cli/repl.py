"""Interactive conversational REPL for the ShipAgent agent.

Provides a terminal-based chat interface with Rich rendering
for previews, progress, and completions.
"""


from rich.console import Console

from src.cli.protocol import ShipAgentClient

console = Console()


async def run_repl(client: ShipAgentClient, session_id: str | None = None) -> None:
    """Run the interactive conversational REPL.

    Args:
        client: The ShipAgentClient implementation (HTTP or in-process).
        session_id: Optional session ID to resume. Creates new if None.
    """
    async with client:
        # Create or resume session
        if session_id is None:
            session_id = await client.create_session(interactive=False)
            console.print(f"[dim]Session: {session_id}[/dim]")

        console.print()
        console.print("[bold]ShipAgent[/bold] v3.0 — Interactive Mode")
        console.print("Type your shipping commands. Ctrl+D to exit.")
        console.print()

        try:
            while True:
                try:
                    user_input = console.input("[bold green]> [/bold green]")
                except EOFError:
                    # Ctrl+D
                    break

                if not user_input.strip():
                    continue

                # Stream agent response
                message_buffer = []
                try:
                    async for event in client.send_message(session_id, user_input):
                        if event.event_type == "agent_message_delta":
                            if event.content:
                                console.print(event.content, end="")
                                message_buffer.append(event.content)
                        elif event.event_type == "tool_call":
                            console.print(
                                f"\n[dim]Tool: {event.tool_name}[/dim]", end=""
                            )
                        elif event.event_type == "done":
                            break
                        elif event.event_type == "error":
                            console.print(
                                f"\n[red]Error: {event.content}[/red]"
                            )
                except KeyboardInterrupt:
                    console.print("\n[yellow]Interrupted[/yellow]")
                    continue

                console.print()  # Newline after streamed response

        finally:
            # Cleanup session
            try:
                await client.delete_session(session_id)
            except Exception:
                pass

        console.print("\n[dim]Session ended.[/dim]")
