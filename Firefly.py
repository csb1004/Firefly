import discord

from firefly.commands import handle_mentioned_message
from firefly.config import DISCORD_BOT_TOKEN
from firefly.polls import enforce_single_vote, restore_poll_tasks
from firefly.storage import (
    get_room_data,
    get_room_key,
    get_user_data,
    record_room_user_message,
)
from firefly.text_utils import clean_discord_content, is_command_text

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True

client = discord.Client(intents=intents)


def _message_mentions_user(message: discord.Message, user: object) -> bool:
    return any(getattr(mention, "id", None) == user.id for mention in message.mentions)


@client.event
async def on_ready():
    print(f"로그인됨: {client.user}")
    await restore_poll_tasks(client)


@client.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    await enforce_single_vote(client, payload)


@client.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    room_key = get_room_key(message)
    room_data = get_room_data(room_key)

    if client.user and _message_mentions_user(message, client.user):
        user_text = clean_discord_content(
            message,
            bot_user_id=client.user.id,
            remove_bot_mention=True,
        )

        if not user_text:
            await message.channel.send("응, 불렀어?")
            return

        display_name = getattr(message.author, "display_name", message.author.name)
        user_data = get_user_data(message.author.id, display_name)

        await handle_mentioned_message(
            message=message,
            user_text=user_text,
            user_data=user_data,
            room_key=room_key,
            room_data=room_data,
            client=client,
        )
        return

    if room_data.get("group_mode", False):
        content = clean_discord_content(message)
        if content and not is_command_text(content):
            record_room_user_message(
                message,
                room_key,
                room_data,
                content=content,
            )


client.run(DISCORD_BOT_TOKEN)
