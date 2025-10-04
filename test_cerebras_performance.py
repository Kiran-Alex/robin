#!/usr/bin/env python3
"""Test Cerebras API performance directly"""
import time
import os
from langchain_cerebras import ChatCerebras
from langchain_core.messages import HumanMessage

# Test API key is set
os.environ["CEREBRAS_API_KEY"] = "csk-c9yrx2tfdrfyted3w5ckvnprm64rh48frrhvpevv9j26982v"

def test_cerebras_direct():
    """Test Cerebras API with simple prompt"""
    print("\n" + "="*60)
    print("TESTING CEREBRAS API DIRECTLY")
    print("="*60)

    llm = ChatCerebras(model="llama-4-maverick-17b-128e-instruct", timeout=30)

    # Test 1: Simple prompt
    print("\n[TEST 1] Simple prompt...")
    start = time.time()
    response = llm.invoke([HumanMessage(content="Say hello in 3 words")])
    elapsed = time.time() - start
    print(f"Response: {response.content}")
    print(f"⏱️  Time: {elapsed:.2f}s")

    # Test 2: Code generation (similar to /generate)
    print("\n[TEST 2] Code generation prompt...")
    start = time.time()
    prompt = """Generate a simple Discord bot with a help command. Return ONLY JSON:
{"files": [{"path": "bot.py", "content": "import discord\\nbot = discord.Client()"}]}"""
    response = llm.invoke([HumanMessage(content=prompt)])
    elapsed = time.time() - start
    print(f"Response length: {len(response.content)} chars")
    print(f"⏱️  Time: {elapsed:.2f}s")

    # Test 3: Command plan (similar to /plan)
    print("\n[TEST 3] Command plan prompt...")
    start = time.time()
    prompt = """Generate Discord bot commands. Return ONLY JSON:
{"prefix":"!","commands":[{"name":"help","description":"Shows commands"}]}"""
    response = llm.invoke([HumanMessage(content=prompt)])
    elapsed = time.time() - start
    print(f"Response: {response.content[:200]}...")
    print(f"⏱️  Time: {elapsed:.2f}s")

    print("\n" + "="*60)

if __name__ == "__main__":
    test_cerebras_direct()
