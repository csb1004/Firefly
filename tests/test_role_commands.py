import asyncio
from types import SimpleNamespace

import discord

from firefly import commands
from firefly.role_commands import _parse_color_value


class FakeChannel:
    def __init__(self):
        self.sent_messages = []

    async def send(self, content=None, **kwargs):
        self.sent_messages.append(content or "<embed>")


class FakeRole:
    def __init__(self, role_id=456, name="운영진", permissions=None):
        self.id = role_id
        self.name = name
        self.mention = f"<@&{role_id}>"
        self.permissions = permissions or discord.Permissions.none()
        self.edit_calls = []

    def is_default(self):
        return False

    async def edit(self, **kwargs):
        self.edit_calls.append(kwargs)
        if "name" in kwargs:
            self.name = kwargs["name"]
        if "permissions" in kwargs:
            self.permissions = kwargs["permissions"]


class FakeMember:
    def __init__(self, user_id=123, name="Alice"):
        self.id = user_id
        self.name = name
        self.display_name = name
        self.mention = f"<@{user_id}>"
        self.added_roles = []
        self.removed_roles = []

    async def add_roles(self, role, **kwargs):
        self.added_roles.append((role, kwargs))

    async def remove_roles(self, role, **kwargs):
        self.removed_roles.append((role, kwargs))


class FakeGuild:
    def __init__(self, member, role):
        self.roles = [role]
        self._member = member
        self._role = role

    def get_member(self, member_id):
        return self._member if member_id == self._member.id else None

    def get_role(self, role_id):
        return self._role if role_id == self._role.id else None


def _message(channel, member, role, *, author_id=None):
    return SimpleNamespace(
        author=SimpleNamespace(
            id=author_id or commands.SPECIAL_USER_ID,
            name="Owner",
            display_name="Owner",
        ),
        channel=channel,
        mentions=[member],
        role_mentions=[role],
        guild=FakeGuild(member, role),
    )


def test_role_command_assigns_role_to_member():
    channel = FakeChannel()
    member = FakeMember()
    role = FakeRole()
    message = _message(channel, member, role)
    client = SimpleNamespace(user=SimpleNamespace(id=999))

    asyncio.run(
        commands.handle_mentioned_message(
            message=message,
            user_text="/역할 부여 <@123> <@&456>",
            user_data={},
            room_key="room-1",
            room_data={},
            client=client,
        )
    )

    assert member.added_roles[0][0] is role
    assert channel.sent_messages == ["…응. <@123>에게 <@&456> 역할을 부여했어."]


def test_role_command_changes_role_color():
    channel = FakeChannel()
    member = FakeMember()
    role = FakeRole()
    message = _message(channel, member, role)
    client = SimpleNamespace(user=SimpleNamespace(id=999))

    asyncio.run(
        commands.handle_mentioned_message(
            message=message,
            user_text="/역할 색 <@&456> #ffaa00",
            user_data={},
            room_key="room-1",
            room_data={},
            client=client,
        )
    )

    assert role.edit_calls[0]["color"] == discord.Color(0xFFAA00)
    assert channel.sent_messages == ["…응. <@&456> 색을 `#FFAA00`로 바꿨어."]


def test_role_color_parser_accepts_natural_color_names_and_loose_hex():
    assert _parse_color_value("하늘색 계열로 해줘") == 0x87CEEB
    assert _parse_color_value("하얀색으로") == 0xFFFFFF
    assert _parse_color_value("ffffff로해줘") == 0xFFFFFF
    assert _parse_color_value("#0af로") == 0x00AAFF


def test_role_command_renames_and_recolors_in_one_message(monkeypatch):
    channel = FakeChannel()
    member = FakeMember()
    role = FakeRole(name="일레이나")
    message = _message(channel, member, role)
    client = SimpleNamespace(user=SimpleNamespace(id=999))

    async def fake_plan_tool_use(**kwargs):
        return commands.ToolPlan(
            mode=commands.PLAN_COMMAND,
            commands=('/역할 일레이나 역할을 "관리자"로 이름 바꿔줘. 색은 하늘색 계열로 해줘',),
            confidence=0.91,
        )

    monkeypatch.setattr(commands, "plan_tool_use", fake_plan_tool_use)

    asyncio.run(
        commands.handle_mentioned_message(
            message=message,
            user_text='일레이나 역할을 "관리자"로 이름 바꿔줘. 색은 하늘색 계열로 해줘',
            user_data={},
            room_key="room-1",
            room_data={},
            client=client,
        )
    )

    assert role.edit_calls[0]["name"] == "관리자"
    assert role.edit_calls[1]["color"] == discord.Color(0x87CEEB)
    assert channel.sent_messages == [
        "…응. `일레이나` 역할 이름을 `관리자`로 바꿨어.",
        "…응. <@&456> 색을 `#87CEEB`로 바꿨어.",
    ]


def test_color_followup_without_role_asks_for_role_instead_of_calling_model(monkeypatch):
    channel = FakeChannel()
    member = FakeMember()
    role = FakeRole()
    message = SimpleNamespace(
        author=SimpleNamespace(
            id=commands.SPECIAL_USER_ID,
            name="Owner",
            display_name="Owner",
        ),
        channel=channel,
        mentions=[],
        role_mentions=[],
        guild=FakeGuild(member, role),
    )
    client = SimpleNamespace(user=SimpleNamespace(id=999))

    async def fail_generate_reply(**kwargs):
        raise AssertionError("color follow-up should not call the model")

    async def fake_plan_tool_use(**kwargs):
        return commands.ToolPlan(
            mode=commands.PLAN_CLARIFY,
            response="…대상 역할을 멘션하거나 정확한 역할 이름을 적어줘.",
            confidence=0.86,
        )

    monkeypatch.setattr(commands, "plan_tool_use", fake_plan_tool_use)
    monkeypatch.setattr(commands, "generate_reply", fail_generate_reply)

    asyncio.run(
        commands.handle_mentioned_message(
            message=message,
            user_text="그러면 ffffff로해줘",
            user_data={},
            room_key="room-1",
            room_data={},
            client=client,
        )
    )

    assert channel.sent_messages == ["…대상 역할을 멘션하거나 정확한 역할 이름을 적어줘."]


def test_role_command_removes_permissions():
    channel = FakeChannel()
    member = FakeMember()
    permissions = discord.Permissions.none()
    permissions.administrator = True
    permissions.manage_messages = True
    role = FakeRole(permissions=permissions)
    message = _message(channel, member, role)
    client = SimpleNamespace(user=SimpleNamespace(id=999))

    asyncio.run(
        commands.handle_mentioned_message(
            message=message,
            user_text="/역할 권한제거 <@&456> 관리자 메시지관리",
            user_data={},
            room_key="room-1",
            room_data={},
            client=client,
        )
    )

    edited_permissions = role.edit_calls[0]["permissions"]
    assert edited_permissions.administrator is False
    assert edited_permissions.manage_messages is False
    assert channel.sent_messages == [
        "…응. <@&456> 역할에서 `administrator, manage_messages` 권한을 제거했어."
    ]


def test_role_permission_parser_ignores_permission_words_in_role_name():
    channel = FakeChannel()
    member = FakeMember()
    permissions = discord.Permissions.none()
    permissions.administrator = True
    permissions.manage_messages = True
    role = FakeRole(name="관리자", permissions=permissions)
    message = _message(channel, member, role)
    client = SimpleNamespace(user=SimpleNamespace(id=999))

    asyncio.run(
        commands.handle_mentioned_message(
            message=message,
            user_text="/역할 권한제거 관리자 메시지관리",
            user_data={},
            room_key="room-1",
            room_data={},
            client=client,
        )
    )

    edited_permissions = role.edit_calls[0]["permissions"]
    assert edited_permissions.administrator is True
    assert edited_permissions.manage_messages is False


def test_role_permission_parser_keeps_permission_alias_suffixes():
    channel = FakeChannel()
    member = FakeMember()
    role = FakeRole()
    message = _message(channel, member, role)
    client = SimpleNamespace(user=SimpleNamespace(id=999))

    asyncio.run(
        commands.handle_mentioned_message(
            message=message,
            user_text="/역할 권한추가 <@&456> 반응추가",
            user_data={},
            room_key="room-1",
            room_data={},
            client=client,
        )
    )

    edited_permissions = role.edit_calls[0]["permissions"]
    assert edited_permissions.add_reactions is True


def test_role_command_rejects_non_special_user():
    channel = FakeChannel()
    member = FakeMember()
    role = FakeRole()
    message = _message(channel, member, role, author_id=123)
    client = SimpleNamespace(user=SimpleNamespace(id=999))

    asyncio.run(
        commands.handle_mentioned_message(
            message=message,
            user_text="/역할 부여 <@123> <@&456>",
            user_data={},
            room_key="room-1",
            room_data={},
            client=client,
        )
    )

    assert member.added_roles == []
    assert channel.sent_messages == ["…그 명령어를 사용할 권한이 없어."]
