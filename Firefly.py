import os
import asyncio
from pathlib import Path

import discord
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()

if not DISCORD_BOT_TOKEN:
    raise ValueError("DISCORD_BOT_TOKEN이 .env에 없습니다.")
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY가 .env에 없습니다.")

client_openai = OpenAI(api_key=OPENAI_API_KEY)

DEFAULT_PROMPT_FILE = Path("prompt.txt")
SPECIAL_PROMPT_FILE = Path("prompt_special.txt")

# 여기에 특정 유저의 디스코드 ID 넣기
SPECIAL_USER_ID = 393724092022390784

LONG_SAM_LINE = (
    "지금당장떠나면아무도다치지않는다그러지않으면너희는모두죽어탐정놀이도이젠끝이다현실로돌아가면"
    "잊지말고전해라스텔라론헌터가너희의마지막을배웅했다는것을소탕시작액션원집행목표고정즉시처단"
    "프로토콜통과초토화작전집행깨어났군한참이나기다렸다우린전에만난적이있지난스텔라론헌터샘이다"
    "일찍이네앞에나타나사실을알려주고싶었어하지만예상보다방해물이많더군열한차례시도했지만모두실패로"
    "끝났지그러는사이에나도모르게이세계와긴밀이연결되어각본의구속에서벗어날수없게됐다엘리오말대로"
    "우리는이꿈의땅에서잊을수없는수확을얻게될테지나에겐그와카프카처럼사람의마음을꿰뚫어보는통찰력도"
    "은랑과블레이드처럼뛰어난특기도없다내가잘하는것들대부분은불쌍히여길필요없는악당에게만적용되지"
    "그러니내가사용할수있는수단도단하나뿐이다네게보여주기위한거야내전부를"
)

def load_text_file(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"{path} 파일을 찾을 수 없어.")
    return path.read_text(encoding="utf-8").strip()

def get_system_prompt(user_id: int) -> str:
    if user_id == SPECIAL_USER_ID:
        return load_text_file(SPECIAL_PROMPT_FILE)
    return load_text_file(DEFAULT_PROMPT_FILE)

def clean_mention(message_content: str, bot_user_id: int) -> str:
    return (
        message_content
        .replace(f"<@{bot_user_id}>", "")
        .replace(f"<@!{bot_user_id}>", "")
        .strip()
    )

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

async def generate_reply(user_message: str, user_id: int) -> str:
    if user_message.strip() == "그 긴거 해줘":
        return LONG_SAM_LINE

    system_prompt = get_system_prompt(user_id)

    response = await asyncio.to_thread(
        client_openai.responses.create,
        model="gpt-5.3-codex",
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    )

    return response.output_text.strip()

@client.event
async def on_ready():
    print(f"로그인됨: {client.user}")

@client.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    if client.user in message.mentions:
        user_text = clean_mention(message.content, client.user.id)

        if not user_text:
            await message.channel.send("응, 불렀어?")
            return

        async with message.channel.typing():
            try:
                reply = await generate_reply(user_text, message.author.id)
                await message.channel.send(reply[:1900])
            except Exception as e:
                print("오류:", e)
                await message.channel.send("…미안. 지금은 조금 불안정해.")

client.run(DISCORD_BOT_TOKEN)