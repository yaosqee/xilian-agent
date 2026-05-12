"""ModelRouter — 混合路由核心，进程内路由"""
import os
import asyncio
from typing import Literal
from dotenv import load_dotenv
from openai import AsyncOpenAI
from ollama import AsyncClient as OllamaClient
from loguru import logger

load_dotenv()

TaskType = Literal[
    "chat", "empathy",
    "proactive_greeting", "tool_result_wrap", "image_response",
    "memory_encoding", "autobiography", "reflection", "dream",
    "reasoning", "code", "planning",
    "personality_check", "prompt_injection_detect", "approval_text",
]

class ModelRouter:
    """
    混合路由拓扑：
    · 核心对话 + 共情 → 过渡期云端 Qwen-Plus → 7/15 后切本地 → 阶段5微调版
    · 自主问候/工具包装/图像回应 → 始终本地优先
    · 记忆编码/自传体/反思/梦幻 → 云端辅助（后台长文）
    · 推理/代码/规划/人设自检/注入检测 → 云端 DeepSeek-V4-Flash
    """

    def __init__(self):
        mode = os.getenv("TRANSITION_MODE", "cloud")
        self.use_local_for_chat = (mode in ("local_base", "finetuned"))

        # 本地客户端
        self.ollama = OllamaClient(host="http://localhost:11434")
        self.local_model = "qwen3:14b"

        # 云端客户端
        self.qwen = AsyncOpenAI(
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        self.qwen_model = "qwen3.6-plus"

        self.ds = AsyncOpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url="https://api.deepseek.com",
        )
        self.ds_model = "deepseek-v4-pro"

        logger.info(
            "ModelRouter 就绪",
            transition_mode=mode,
            use_local_for_chat=self.use_local_for_chat,
        )

    # ========== 路由表 ==========
    ROUTE_LOCAL_FIRST = {"proactive_greeting", "tool_result_wrap", "image_response"}
    ROUTE_CLOUD_QWEN = {"memory_encoding", "autobiography", "reflection", "dream"}
    ROUTE_CLOUD_DS = {"reasoning", "code", "planning",
                      "personality_check", "prompt_injection_detect", "approval_text",
                      "empathy"}

    async def route(self, task_type: TaskType, messages: list, **kwargs):
        # --- 核心对话：过渡期路由 ---
        if task_type == "chat":
            if self.use_local_for_chat:
                try:
                    return await self._call_ollama(messages, **kwargs)
                except Exception as e:
                    logger.warning("本地模型不可用，fallback 云端", error=str(e))
                    return await self._call_qwen(messages, **kwargs)
            else:
                logger.info("过渡期核心对话走云端", task_type=task_type)
                return await self._call_qwen(messages, **kwargs)

        # --- 始终本地优先 ---
        if task_type in self.ROUTE_LOCAL_FIRST:
            try:
                return await self._call_ollama(messages, **kwargs)
            except Exception as e:
                logger.warning(f"{task_type} 本地不可用，fallback 云端", error=str(e))
                return await self._call_qwen(messages, **kwargs)

        # --- 云端辅助（后台长文） ---
        if task_type in self.ROUTE_CLOUD_QWEN:
            return await self._call_qwen(messages, **kwargs)

        # --- 云端推理 ---
        if task_type in self.ROUTE_CLOUD_DS:
            return await self._call_ds(messages, **kwargs)

        # fallback
        logger.warning("未知任务类型，fallback 云端", task_type=task_type)
        return await self._call_qwen(messages, **kwargs)

    # ========== 底层调用 ==========

    async def _call_ollama(self, messages: list, timeout: int = 120, **kwargs):
        response = await asyncio.wait_for(
            self.ollama.chat(
                model=self.local_model,
                messages=messages,
                options={"temperature": kwargs.get("temperature", 0.7)},
            ),
            timeout=timeout,
        )
        return response["message"]["content"]

    async def _call_qwen(self, messages: list, timeout: int = 60, **kwargs):
        response = await asyncio.wait_for(
            self.qwen.chat.completions.create(
                model=self.qwen_model,
                messages=messages,
                temperature=kwargs.get("temperature", 0.7),
                stream=kwargs.get("stream", False),
            ),
            timeout=timeout,
        )
        if kwargs.get("stream"):
            return response
        return response.choices[0].message.content

    async def _call_ds(self, messages: list, timeout: int = 60, **kwargs):
        response = await asyncio.wait_for(
            self.ds.chat.completions.create(
                model=self.ds_model,
                messages=messages,
                temperature=kwargs.get("temperature", 0.3),
            ),
            timeout=timeout,
        )
        return response.choices[0].message.content

    # ========== 手动覆盖 ==========

    async def route_with_override(self, task_type, messages, model_override=None, **kwargs):
        """允许手动指定模型，用于对比测试"""
        if model_override == "local":
            return await self._call_ollama(messages, **kwargs)
        elif model_override == "qwen":
            return await self._call_qwen(messages, **kwargs)
        elif model_override == "ds":
            return await self._call_ds(messages, **kwargs)
        return await self.route(task_type, messages, **kwargs)
