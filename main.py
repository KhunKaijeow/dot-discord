import sys

from src.config import DISCORD_TOKEN, GEMINI_API_KEY


def main() -> None:
    missing_variables = [
        name
        for name, value in (
            ("DISCORD_TOKEN", DISCORD_TOKEN),
            ("GEMINI_API_KEY", GEMINI_API_KEY),
        )
        if not value
    ]

    if missing_variables:
        print(
            "[ERROR] Missing required environment variables: "
            + ", ".join(missing_variables),
            file=sys.stderr,
        )
        raise SystemExit(1)

    # Import after validation so Railway gets a clear startup error when a
    # required secret has not been configured.
    from src.bot import bot

    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
