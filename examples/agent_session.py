from __future__ import annotations

from datetime import timedelta

from memory_mini import Store


def main() -> None:
    with Store("agent-session.db") as memory:
        session_slug = "session-end-2026-05-01-1"
        memory.store(
            session_slug,
            "Shipped the import cleanup and verified lint, types, and tests.",
            "sessions/public-site",
        )

        for entry in memory.list("sessions/public-site"):
            print(f"{entry.key}: {entry.value}")

        memory.soft_delete("session-end-2026-04-01-1", "sessions/public-site")
        removed = memory.cleanup(retention=timedelta(days=14))
        print(f"cleaned={removed}")


if __name__ == "__main__":
    main()
