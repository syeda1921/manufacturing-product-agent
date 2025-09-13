from dotenv import load_dotenv
import os
import sys
from pathlib import Path

# Force Python to use your local ./agents package first
_THIS_DIR = Path(__file__).resolve().parent
_LOCAL_AGENTS_DIR = _THIS_DIR / "agents"
if _LOCAL_AGENTS_DIR.exists():
    sys.path.insert(0, str(_THIS_DIR))
    sys.path.insert(0, str(_LOCAL_AGENTS_DIR))


from agents import Agent, Runner, AsyncOpenAI, OpenAIChatCompletionsModel, set_tracing_disabled, GuardrailFunctionOutput
from agents import function_tool, handoff, InputGuardrail   
from agents.exceptions import InputGuardrailTripwireTriggered
from pydantic import BaseModel, Field
from dataclasses import dataclass
import asyncio
import json 

_ = load_dotenv()

# Make sure your .env has GEMINI_API_KEY=xxxx
GEMINI_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEYS")


# Guardrails

class Acedemic_research(BaseModel):  
    is_researchWork: bool = Field(..., description="Acedemic research relevent questions")
    reasoning: str


guardrail_agent = Agent(
    name="Guardrail check",
    instructions="Check if the user is asking to generate content of academic research.",
    output_type=Acedemic_research,
    
)

# Tracing disabled to stop logs from connecting to the open ai server
set_tracing_disabled(disabled=True)

# 1. Which LLM Service?
external_client: AsyncOpenAI = AsyncOpenAI(
    api_key=GEMINI_KEY,  
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
)

# 2. Which LLM Model?
llm_model: OpenAIChatCompletionsModel = OpenAIChatCompletionsModel(
    model="gemini-2.5-flash",
    openai_client=external_client
)

# Now that llm_model exists, wire it into guardrail_agent
guardrail_agent.model = llm_model  # ensure guardrail uses Gemini client



# Example function tool
@function_tool
def estimate_cost(units: int, cost_per_unit: float) -> dict:
    """
    Estimate the total cost of producing a number of units.
    Args:
        units (int): number of items to produce
        cost_per_unit (float): cost of making one item
    Returns:
        dict: total cost calculation
    """
    total = units * cost_per_unit
    return {"units": units, "cost_per_unit": cost_per_unit, "total_cost": total}



# making the agents

product_owner: Agent = Agent(
    name="product owner",
    handoff_description="Special Agent for product's execution planning, success, and drawbacks.",  
    instructions="You are a helpful product owner that assists in initiating to executing any product related to manufacturing industry.",
    model=llm_model,
    tools=[estimate_cost]
)

product_reporter: Agent = Agent(
    name="product reporter",
    handoff_description="Special Agent for product data reporting",
    instructions="You are a helpful product reporter that assists in making full report based on the product discussed.",
    model=llm_model,
    tools=[estimate_cost]
)

project_finance_manager: Agent = Agent(
    name="product finance manager",
    handoff_description="Special Agent for product's financial affairs.",
    instructions="You are a helpful product finance manager that assists in sorting the cost of the project execution.",
    model=llm_model,
    tools=[estimate_cost]
)

# guardrail
async def researchWork_guardrail(ctx, agent, input_data):
    result = await Runner.run(guardrail_agent, input_data, context=ctx.context)
    final_output = result.final_output_as(Acedemic_research)
    print(final_output)
    return GuardrailFunctionOutput(
        output_info=final_output,
        tripwire_triggered=final_output.is_researchWork,
    )

# triage_agent application
triage_agent = Agent(
    name="Triage Agent",
    instructions="You determine which agent to use based on the user's product question"
    "You determine which agent to use based on the user's product question. "
    "If the user asks about estimating costs, you MUST call the 'estimate_cost' tool. "
    "Do not answer cost questions yourself.",
    handoffs=[project_finance_manager, product_owner, product_reporter],
    # Use the guardrail.
    input_guardrails=[
        InputGuardrail(guardrail_function=researchWork_guardrail),
    ],
    model=llm_model,
    tools=[estimate_cost]
)

# applying chainlit 

import chainlit as cl

conversation_history = []


# Welcome message 
@cl.on_chat_start
async def on_start():
    await cl.Message(
        content=(
            "**Hi! I’m your Product Triage Agent.**\n\n"
            "I can:\n"
            "• Route your question to the right specialist (Product Owner, Reporter, Finance Manager)\n"
            "• Call handy tools like a quick cost estimator (try: *Estimate the cost for 100 units at 5 each*)\n\n"
            "Ask me anything about your manufacturing product plans, reports, costs; however, no acedemic research question can be asked, they will be prevented."
        )
    ).send()


@cl.on_message
async def main(message: cl.Message):
    global conversation_history

    # Use the async Runner.run to avoid blocking the event loop.
    try:
        if len(conversation_history) == 0:
            result = await Runner.run(triage_agent, message.content)
        else:
            result = await Runner.run(
                triage_agent,
                conversation_history + [{'content': message.content, 'role': 'user'}]
            )

        # Refresh history from the result each turn.
        conversation_history = result.to_input_list()

        # Get which agent answered
        agent_name = result.last_agent.name if result.last_agent else "Unknown agent"

        # CHANGED: pretty-print dict/list outputs from tools
        output = result.final_output
        if isinstance(output, (dict, list)):
            pretty_output = "```json\n" + json.dumps(output, ensure_ascii=False, indent=2) + "\n```"
        else:
            pretty_output = str(output)

        await cl.Message(
            content=f"**{agent_name}** handled your question:\n\n{pretty_output}"
        ).send()

    except InputGuardrailTripwireTriggered:
        await cl.Message(
            content="Sorry, but I'm not allowed to respond to any academic research question."
        ).send()
