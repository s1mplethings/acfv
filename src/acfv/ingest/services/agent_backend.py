import json
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver
from .tools import rate_clip as rate_clip_impl

# 兼容保留原始评分工具
@tool
def rate_clip(path: str) -> str:
    """对给定视频片段打分。参数: path (保留, 供需要时调用)"""
    result = rate_clip_impl(path)
    return json.dumps(result, ensure_ascii=False)

def get_llm(model: str = "qwen2.5:7b-instruct"):
    return ChatOpenAI(
        base_url="http://localhost:11434/v1",
        api_key="ollama",
        model=model,
        temperature=0.2,
    )

class AgentBackend:
    def __init__(self, model: str = "qwen2.5:7b-instruct"):
        self.llm = get_llm(model)
        self.checkpointer = MemorySaver()
        tools = [rate_clip]
        try:
            # 动态加载应用动作工具
            from .app_actions import get_agent_tools
            tools.extend(get_agent_tools())
        except Exception:
            pass
        self.agent = create_react_agent(self.llm, tools, checkpointer=self.checkpointer)

    def ask(self, query: str, thread_id: str = "gui") -> str:
        out = self.agent.invoke(
            {"input": query},
            config={"configurable": {"thread_id": thread_id}},
        )
        return out.get("output") or out.get("final_output") or str(out)
