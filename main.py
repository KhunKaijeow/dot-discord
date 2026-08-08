import logging
import sys

from src.config import DISCORD_TOKEN, missing_required_environment_variables


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("javis.startup")


def main() -> None:
    missing_variables = missing_required_environment_variables()

    if missing_variables:
        logger.error("Missing required environment variables: %s", ", ".join(missing_variables))
        raise SystemExit(1)

    # Import after validation so Railway gets a clear startup error when a
    # required secret has not been configured.
    from src.bot import bot

    assert DISCORD_TOKEN is not None
    # The root logger above owns the single stdout handler. Disabling the
    # handler installed by discord.py prevents duplicate lines on Railway.
    bot.run(DISCORD_TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
