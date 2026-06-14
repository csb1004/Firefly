import discord

from .config import SPECIAL_USER_ID
from .storage import update_user_data
from .user_targets import nickname_conflict_message, resolve_explicit_user_target


async def handle_nickname_command(
    *,
    message: discord.Message,
    argument_text: str,
    user_data: dict,
    client: discord.Client,
    special_user: bool,
) -> None:
    argument_text = argument_text.strip()
    if not argument_text:
        await message.channel.send("…호칭을 비워둘 수는 없어.")
        return

    if not special_user:
        new_nickname = argument_text
        conflict_message = nickname_conflict_message(new_nickname, message.author.id)
        if conflict_message:
            await message.channel.send(conflict_message)
            return

        user_data["nickname"] = new_nickname
        update_user_data(message.author.id, user_data)
        await message.channel.send(f"응. 이제부터는 {new_nickname}(이)라고 불러볼게.")
        return

    target, new_nickname, error_message = await resolve_explicit_user_target(
        message=message,
        client=client,
        argument_text=argument_text,
    )
    if error_message:
        await message.channel.send(error_message)
        return

    if target is None:
        await message.channel.send("…대상과 새 호칭을 같이 적어줘. 예: `/호칭 @유저 이카`")
        return

    if target.user_id == SPECIAL_USER_ID:
        await message.channel.send("…그 대상의 호칭은 변경할 수 없어.")
        return

    new_nickname = (new_nickname or "").strip()
    if not new_nickname:
        await message.channel.send("…새 호칭을 같이 적어줘. 예: `/호칭 @유저 이카`")
        return

    conflict_message = nickname_conflict_message(new_nickname, target.user_id)
    if conflict_message:
        await message.channel.send(conflict_message)
        return

    target_data = dict(target.user_data or get_user_data(target.user_id, target.display_name))
    target_data["nickname"] = new_nickname
    update_user_data(target.user_id, target_data)
    await message.channel.send(f"…응. {target.display_name}의 호칭을 `{new_nickname}`로 바꿨어.")
