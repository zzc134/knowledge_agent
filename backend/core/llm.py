from openai import AsyncOpenAI
from anthropic import AsyncAnthropic
from config import get_settings

settings = get_settings()

openai_client: AsyncOpenAI | None = None
anthropic_client: AsyncAnthropic | None = None


def _get_openai() -> AsyncOpenAI:
    global openai_client
    if openai_client is None:
        openai_client = AsyncOpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
        )
    return openai_client


async def llm_call(
    system_prompt: str,
    user_message: str,
    provider: str = "deepseek",
    model: str = "deepseek-chat",
) -> str:
    """统一的 LLM 调用入口，支持 deepseek/openai/anthropic"""
    if provider in ("deepseek", "openai"):
        client = _get_openai()
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.0,
        )
        return response.choices[0].message.content or ""

    elif provider == "anthropic":
        global anthropic_client
        if anthropic_client is None:
            anthropic_client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await anthropic_client.messages.create(
            model=model,
            max_tokens=2000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        return response.content[0].text

    else:
        raise ValueError(f"Unknown provider: {provider}")


async def llm_chat(
    messages: list[dict],
    provider: str = "deepseek",
    model: str = "deepseek-chat",
) -> str:
    """支持完整 messages 列表的 LLM 调用——多轮对话用"""
    if provider in ("deepseek", "openai"):
        client = _get_openai()
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.0,
        )
        return response.choices[0].message.content or ""

    elif provider == "anthropic":
        global anthropic_client
        if anthropic_client is None:
            anthropic_client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        system_msg = next((m for m in messages if m["role"] == "system"), None)
        user_msgs = [m for m in messages if m["role"] != "system"]
        response = await anthropic_client.messages.create(
            model=model,
            max_tokens=2000,
            system=system_msg["content"] if system_msg else "",
            messages=user_msgs,
        )
        return response.content[0].text

    raise ValueError(f"Unknown provider: {provider}")


async def llm_chat_with_retry(
    messages: list[dict],
    provider: str = "deepseek",
    model: str = "deepseek-chat",
    max_retries: int = 3,
) -> str:
    """带指数退避重试的 LLM 调用"""
    import asyncio as _asyncio

    last_error = None
    for attempt in range(max_retries):
        try:
            return await llm_chat(messages, provider, model)
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                wait = 2**attempt
                await _asyncio.sleep(wait)
    raise last_error
